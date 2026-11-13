"""외부 API·DB를 실제 호출하지 않는 모의 회귀 테스트."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app, FactInput, create_fact_sheet


class ContractTests(unittest.TestCase):
    def test_fact_input_constraints(self):
        with self.assertRaises(Exception):
            FactInput(
                origin="A", destination="B", distance_m=0,
                duration_seconds=-1, source_url="a"
            )

    def test_fact_sheet_no_invented_values(self):
        fact = {
            "id": 1, "origin": "서울역", "destination": "잠실역",
            "distance_m": 1000, "duration_seconds": 300,
            "retrieved_at": "2026-10-20", "source_url": "https://example.org",
        }
        self.assertEqual(create_fact_sheet(fact)["duration_seconds"], 300)

    def test_draft_model_default_and_environment_override(self):
        import os
        from contextlib import contextmanager
        from app.main import DraftInput, generate_draft

        fact = {
            "id": 1, "origin": "서울역", "destination": "잠실역",
            "distance_m": 1000, "duration_seconds": 300,
            "retrieved_at": "2026-11-13", "source_url": "https://example.org",
        }
        connection = MagicMock()
        connection.cursor.return_value.lastrowid = 7

        @contextmanager
        def fake_db():
            yield connection

        for configured_model in (None, "custom-model"):
            with self.subTest(configured_model=configured_model):
                environment = {"OPENAI_API_KEY": "test-only"}
                if configured_model:
                    environment["OPENAI_MODEL"] = configured_model
                with patch.dict(os.environ, environment, clear=True), \
                     patch("app.main.get_fact", return_value=fact), \
                     patch("app.main.db", fake_db), \
                     patch("openai.OpenAI") as client:
                    completion = client.return_value.chat.completions.create
                    completion.return_value.choices[0].message.content = "제목\n본문"
                    result = generate_draft(DraftInput(fact_id=1))
                arguments = completion.call_args.kwargs
                self.assertEqual(arguments["model"], configured_model or "gpt-6-luna")
                self.assertEqual(arguments["temperature"], 0)
                if configured_model:
                    self.assertNotIn("reasoning_effort", arguments)
                else:
                    self.assertEqual(arguments["reasoning_effort"], "none")
                self.assertEqual(result["status"], "review")
                self.assertEqual(result["body"], "제목\n본문")

    def test_approval_blocks_failed_review(self):
        from contextlib import contextmanager

        class Cursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, values):
                self.calls.append(sql)

            def fetchone(self):
                return ("review",) if len(self.calls) == 1 else (0,)

        cursor = Cursor()

        class Connection:
            def cursor(self):
                return cursor

        @contextmanager
        def fake_db():
            yield Connection()

        with patch("app.main.db", fake_db):
            with TestClient(app) as client:
                response = client.post("/drafts/1/approve")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            any("UPDATE news_drafts" in query for query in cursor.calls)
        )


class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_api_key_is_safe_failure(self):
        import os
        from app.kakao_collector import collect_route, TrafficCollectionError
        with patch.dict(os.environ, {"KAKAO_REST_API_KEY": ""}):
            with self.assertRaises(TrafficCollectionError):
                await collect_route("서울역", "잠실역")

    async def test_collector_extracts_documented_summary(self):
        import os
        from app.kakao_collector import collect_route

        class Response:
            def __init__(self, data):
                self.data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self.data

        class Client:
            def __init__(self):
                self.counter = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, url, **kwargs):
                self.counter += 1
                if self.counter <= 2:
                    return Response({"documents": [{"x": "127.0", "y": "37.5"}]})
                return Response({
                    "routes": [{
                        "result_code": 0,
                        "summary": {"distance": 3200, "duration": 570},
                    }]
                })

        with patch.dict(os.environ, {"KAKAO_REST_API_KEY": "fake_test_only"}):
            with patch("httpx.AsyncClient", return_value=Client()):
                result = await collect_route("서울역", "잠실역")
        self.assertEqual(result["distance_m"], 3200)
        self.assertEqual(result["duration_seconds"], 570)


if __name__ == "__main__":
    unittest.main()
