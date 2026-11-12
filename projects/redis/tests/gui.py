# [gui.py] 브라우저로 Mini Redis 를 눌러 보며 시험하는 GUI 실행기
#
# 실행: projects/redis 에서  python -m tests.gui            → 브라우저로 http://127.0.0.1:6390 열기
#       포트를 바꾸려면      python -m tests.gui --port 7000
#
# ■ 왜 따로 실행기가 필요한가
#   브라우저는 다른 출처(origin)의 서버에 PUT · DELETE 를 보내기 전에 OPTIONS 로 허락을 먼저 묻는다(CORS).
#   Mini Redis 서버는 dev 와 맞춰 OPTIONS 에 405 로 답하므로, 다른 곳에서 연 HTML 은 PUT · DELETE 를 보낼 수 없다.
#   → 이 실행기는 "Mini Redis 서버 + GET / 에서 gui.html 내주기" 를 한 서버로 띄운다.
#     HTML 과 API 가 같은 출처라 CORS 가 필요 없고, mini_redis/ 코드는 한 줄도 바꾸지 않는다.
#
# ■ 무엇을 띄우나
#   - 저장소 MiniRedis() 하나 (이 실행기 전용, 끄면 데이터도 사라짐)
#   - MiniRedisServer (연결 대기열 · 1초 주기 삭제 스레드까지 실제 서버와 같음)
#   - 요청 처리기만 GuiHandler 로 바꿔 끼움: GET / 는 HTML, 나머지는 원래 Handler 가 그대로 처리
#
# 파일 이름이 test*.py 가 아니라서 python -m unittest 가 이 파일을 테스트로 실행하지는 않는다.

import argparse
import pathlib

from mini_redis.server import Handler, MiniRedisServer
from mini_redis.store import MiniRedis

PAGE = pathlib.Path(__file__).with_name("gui.html")  # 같은 폴더의 화면 파일


class GuiHandler(Handler):
    """GET / (또는 /gui) 에서만 화면을 내주고, 나머지 요청은 Mini Redis 서버 Handler 가 그대로 처리한다"""

    def do_GET(self):
        if self.path.split("?", 1)[0] not in ("/", "/gui"):
            return super().do_GET()  # /keys/... · /health 는 실제 서버와 똑같이
        data = PAGE.read_bytes()  # 요청마다 읽는다 → gui.html 을 고치고 새로고침만 하면 바로 반영
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")  # 고친 화면이 브라우저 캐시 때문에 안 보이는 일이 없게
        self.end_headers()
        self.wfile.write(data)


# GUI 서버 생성 (port=0 이면 빈 포트 자동 선택 → 테스트용)
def create_gui_server(store, host="127.0.0.1", port=6390):
    server = MiniRedisServer(store, (host, port))
    server.RequestHandlerClass = GuiHandler  # 요청이 올 때마다 이 클래스로 처리기를 만든다
    return server


# 명령줄 실행 시작점. 기본 127.0.0.1 — 같은 컴퓨터의 브라우저에서만 열린다
def main():
    parser = argparse.ArgumentParser(description="Mini Redis 테스트 GUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6390)
    args = parser.parse_args()
    server = create_gui_server(MiniRedis(), args.host, args.port)
    print(f"Mini Redis 테스트 GUI: http://{args.host}:{args.port}  (끄려면 Ctrl+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
