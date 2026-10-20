"""교통 뉴스 과제용 FastAPI. 운영 배포 금지: 검수자 인증 미구현."""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
app = FastAPI(title="교통정보 뉴스 미니 서비스")


@contextmanager
def db():
    import mysql.connector
    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE", "traffic_news_assignment"),
    )
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class FactInput(BaseModel):
    origin: str = Field(min_length=2, max_length=100)
    destination: str = Field(min_length=2, max_length=100)
    distance_m: int = Field(gt=0)
    duration_seconds: int = Field(ge=0)
    source_url: str = Field(min_length=10, max_length=500)


class DraftInput(BaseModel):
    fact_id: int = Field(gt=0)


class ReviewInput(BaseModel):
    passed: bool
    reviewer_note: str = Field(min_length=5)


class CollectRequest(BaseModel):
    origin: str = Field(min_length=2, max_length=100)
    destination: str = Field(min_length=2, max_length=100)


@app.get("/")
def home():
    return {"service": "traffic_news_assignment", "routes": ["/facts", "/drafts", "/docs"]}


@app.post("/facts", status_code=201)
def create_fact(fact: FactInput):
    with db() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO traffic_facts (origin,destination,distance_m,duration_seconds,retrieved_at,source_url) VALUES (%s,%s,%s,%s,%s,%s)",
            (fact.origin, fact.destination, fact.distance_m,
             fact.duration_seconds, datetime.now(timezone.utc).replace(tzinfo=None), fact.source_url),
        )
        return {"id": cursor.lastrowid}


@app.get("/facts")
def list_facts():
    with db() as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM traffic_facts ORDER BY id DESC LIMIT 100")
        return {"items": cursor.fetchall()}


@app.get("/facts/{fact_id}")
def get_fact(fact_id: int):
    with db() as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM traffic_facts WHERE id=%s", (fact_id,))
        result = cursor.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Fact not found")
        return result


@app.put("/facts/{fact_id}")
def update_fact(fact_id: int, fact: FactInput):
    with db() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "UPDATE traffic_facts SET origin=%s,destination=%s,distance_m=%s,duration_seconds=%s,source_url=%s WHERE id=%s",
            (fact.origin, fact.destination, fact.distance_m,
             fact.duration_seconds, fact.source_url, fact_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Fact not found")
        return {"updated": fact_id}


@app.delete("/facts/{fact_id}")
def delete_fact(fact_id: int):
    import mysql.connector
    with db() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM traffic_facts WHERE id=%s", (fact_id,))
        except mysql.connector.IntegrityError as error:
            raise HTTPException(status_code=409, detail="Connected draft exists") from error
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Fact not found")
        return {"deleted": fact_id}


def create_fact_sheet(fact):
    return {
        "fact_id": fact["id"], "origin": fact["origin"],
        "destination": fact["destination"], "distance_m": fact["distance_m"],
        "duration_seconds": fact["duration_seconds"],
        "retrieved_at": str(fact["retrieved_at"]), "source_url": fact["source_url"],
    }


@app.post("/drafts", status_code=201)
def generate_draft(data: DraftInput):
    from openai import OpenAI
    fact = get_fact(data.fact_id)
    sheet = create_fact_sheet(fact)
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")
    try:
        result = OpenAI().chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            messages=[
                {"role": "system", "content": (
                    "한국어 교통 뉴스 초안을 작성하라. 사실표의 수치만 사용하고 "
                    "근거 없는 인과관계·전망·인터뷰·비교값을 만들지 마라. "
                    "첫 줄은 제목, 다음은 본문. 출처와 조회 시각, 단일 경로 한계를 명시하라."
                )},
                {"role": "user", "content": json.dumps(sheet, ensure_ascii=False)},
            ],
            temperature=0,
        )
        output = (result.choices[0].message.content or "").strip()
    except Exception as error:
        raise HTTPException(status_code=502, detail="AI generation failed") from error
    if not output:
        raise HTTPException(status_code=502, detail="Empty AI response")
    title = output.splitlines()[0][:255]
    with db() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "INSERT INTO news_drafts(fact_id,title,body,status) VALUES (%s,%s,%s,%s)",
            (data.fact_id, title, output, "review"),
        )
        return {
            "id": cursor.lastrowid, "title": title, "body": output,
            "status": "review", "fact_sheet": sheet,
        }


@app.get("/drafts")
def list_drafts():
    with db() as connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id,fact_id,title,body,status,created_at FROM news_drafts ORDER BY id DESC LIMIT 100"
        )
        return {"items": cursor.fetchall()}


@app.post("/drafts/{draft_id}/review")
def review_draft(draft_id: int, review: ReviewInput):
    with db() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT id,status FROM news_drafts WHERE id=%s FOR UPDATE", (draft_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found")
        if row[1] == "approved":
            raise HTTPException(status_code=409, detail="Approved draft cannot be reviewed again")
        cursor.execute(
            "INSERT INTO draft_reviews (draft_id,passed,reviewer_note) VALUES (%s,%s,%s)",
            (draft_id, review.passed, review.reviewer_note),
        )
        cursor.execute(
            "UPDATE news_drafts SET status=%s WHERE id=%s",
            ("review" if review.passed else "held", draft_id),
        )
        return {
            "draft_id": draft_id,
            "review_passed": review.passed,
            "status": "review" if review.passed else "held",
        }


@app.post("/drafts/{draft_id}/approve")
def approve_draft(draft_id: int):
    with db() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT status FROM news_drafts WHERE id=%s FOR UPDATE", (draft_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found")
        if row[0] != "review":
            raise HTTPException(status_code=409, detail="Draft is not pending review")
        cursor.execute(
            "SELECT passed FROM draft_reviews WHERE draft_id=%s ORDER BY id DESC LIMIT 1",
            (draft_id,),
        )
        latest = cursor.fetchone()
        if not latest or not bool(latest[0]):
            raise HTTPException(
                status_code=400,
                detail="Human review required; failed review blocks approval",
            )
        cursor.execute(
            "UPDATE news_drafts SET status='approved' WHERE id=%s", (draft_id,)
        )
        return {"id": draft_id, "status": "approved"}


@app.post("/collect", status_code=201)
async def collect_and_store(data: CollectRequest):
    """명시적으로 호출한 경우에만 Kakao API에서 조회해 MySQL에 저장."""
    from app.kakao_collector import collect_route, TrafficCollectionError
    try:
        measured = await collect_route(data.origin, data.destination)
    except TrafficCollectionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    saved = create_fact(FactInput(**measured))
    return {"id": saved["id"], "source": "Kakao Mobility", "result": measured}
