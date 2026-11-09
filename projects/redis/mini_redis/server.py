# [server.py] Mini Redis HTTP JSON API — 외부 프로그램이 HTTP로 저장소를 사용
#
#   GET    /keys/{key}          값 조회
#   PUT    /keys/{key}          값 저장   body {"value": ..., "ttl": 초(선택)}
#   DELETE /keys/{key}          삭제(무효화)
#   GET    /keys/{key}/ttl      남은 만료 시간
#   POST   /keys/{key}/expire   만료 시간 설정   body {"ttl": 초}
#
# 실행: projects/redis 에서  python -m mini_redis.server --port 6380


# 저장소를 감싼 HTTP 서버 객체 생성
def create_server(store, host="127.0.0.1", port=6380):
    raise NotImplementedError("TODO")


# 명령줄 실행 시작점
def main():
    raise NotImplementedError("TODO")


if __name__ == "__main__":
    main()
