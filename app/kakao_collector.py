"""카카오 Local 장소 검색과 Mobility 자동차 길찾기 요약 수집."""
import os
import httpx

LOCAL_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"


class TrafficCollectionError(Exception):
    """외부 입력/키를 노출하지 않는 수집 오류."""


async def _find_coordinates(client, query, headers):
    response = await client.get(
        LOCAL_SEARCH_URL, params={"query": query, "size": 1}, headers=headers
    )
    response.raise_for_status()
    documents = response.json().get("documents") or []
    if not documents:
        raise TrafficCollectionError("장소 검색 결과가 없습니다.")
    try:
        return float(documents[0]["x"]), float(documents[0]["y"])
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise TrafficCollectionError("장소 좌표를 확인할 수 없습니다.") from error


async def collect_route(origin, destination):
    key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not key:
        raise TrafficCollectionError("카카오 REST API 키가 설정되지 않았습니다.")
    headers = {"Authorization": f"KakaoAK {key}"}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            start = await _find_coordinates(client, origin, headers)
            end = await _find_coordinates(client, destination, headers)
            response = await client.get(
                DIRECTIONS_URL,
                params={
                    "origin": f"{start[0]},{start[1]}",
                    "destination": f"{end[0]},{end[1]}",
                    "priority": "RECOMMEND",
                },
                headers=headers,
            )
            response.raise_for_status()
            routes = response.json().get("routes") or []
            if not routes or routes[0].get("result_code") != 0:
                raise TrafficCollectionError("자동차 경로 조회에 실패했습니다.")
            summary = routes[0].get("summary") or {}
            distance, duration = summary.get("distance"), summary.get("duration")
            if (
                not isinstance(distance, int) or distance <= 0
                or not isinstance(duration, int) or duration < 0
            ):
                raise TrafficCollectionError("경로 수치가 유효하지 않습니다.")
            return {
                "origin": origin,
                "destination": destination,
                "distance_m": distance,
                "duration_seconds": duration,
                "source_url": DIRECTIONS_URL,
            }
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise TrafficCollectionError("외부 교통정보 요청 중 오류가 발생했습니다.") from error
