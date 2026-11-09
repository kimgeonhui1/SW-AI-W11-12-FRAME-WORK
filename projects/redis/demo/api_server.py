# [api_server.py] 기능 테스트용 간단한 API — 느린 데이터 조회 응답을 Mini Redis에 캐시해서 활용
#
#   GET /items/{id}            Mini Redis 캐시 사용 (없으면 느린 조회 후 저장)
#   GET /items/{id}?cache=off  캐시 없이 매번 느린 조회 (성능 비교용)
#
# 실행: projects/redis 에서  python -m demo.api_server --port 8000 --redis http://127.0.0.1:6380


# 느린 원본 데이터 조회 (DB나 외부 API 호출을 흉내)
def fetch_item(item_id):
    raise NotImplementedError("TODO")


# 캐시를 먼저 보고, 없으면 원본 조회 후 Mini Redis에 저장
def get_item_cached(item_id):
    raise NotImplementedError("TODO")


# 명령줄 실행 시작점
def main():
    raise NotImplementedError("TODO")


if __name__ == "__main__":
    main()
