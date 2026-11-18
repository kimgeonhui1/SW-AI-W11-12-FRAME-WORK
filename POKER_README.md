# Jungle Poker Lab

Mini React · Mini Redis · Mini DBMS를 연결한 가상 칩 2인 포커입니다. `room.html`은 사람 간 방 대전, `poker.html`은 봇과 연습 모드입니다.

## 설치와 실행

Git, Python 3.10 이상(이번 검증: Windows Python 3.13.7), 화면 로직 테스트용 Node.js가 필요합니다. Python은 표준 라이브러리만 사용하며 pip/npm 설치가 필요 없습니다. Python 설치 시 PATH 추가를 선택하고 `python --version`을 확인하세요. Store 별칭만 있다면 실제 Python을 설치하거나 설치된 실행 파일 경로를 사용하세요.

```powershell
git clone https://github.com/a01030704572-bit/jungle-poker-lab.git
cd jungle-poker-lab
git switch -c feat/poker-ui
```

저장소 루트에서 PowerShell 창 네 개를 열고 각각 실행합니다. 초기 DB 파일은 필요 없으며 아래 폴더에 자동 생성됩니다. 기존 개인 DB나 게스트 데이터를 복사하지 마세요.

```powershell
# 창 1
cd projects/dbms
python -m mini_dbms.server --data-dir "$env:USERPROFILE\poker-lab-data" --host 127.0.0.1 --port 18783

# 창 2
cd projects/redis
python -m mini_redis.server --host 127.0.0.1 --port 6382

# 창 3
cd projects/poker_demo
python server.py --host 127.0.0.1 --port 18784 --dbms http://127.0.0.1:18783 --redis http://127.0.0.1:6382

# 창 4
cd projects/react
python -m http.server 5500 --bind 127.0.0.1
```

[대전 화면](http://127.0.0.1:5500/room.html)에 접속합니다. 두 번째 게스트는 시크릿 창이나 `room.html?guest=2`를 사용합니다. 종료는 각 창에서 Ctrl+C입니다.

LAN에서는 서버 PC의 창 3·4만 `--host 0.0.0.0`, `--bind 0.0.0.0`으로 바꿉니다. DBMS·Redis는 루프백을 유지합니다. 두 PC 모두 `http://<서버 IPv4>:5500/room.html`에 접속하며 개인 네트워크 방화벽의 5500·18784 허용이 필요합니다. UI만 자신의 PC에서 실행하면 `room.html?api=http://<서버 IPv4>:18784`로 접속합니다. 상세 명령은 [UI_HANDOFF.md](UI_HANDOFF.md)를 참고하세요.

## 협업

- 김준우(`molru-1`): `feat/poker-ui`에서 UI 작업 후 `main` 대상 PR.
- 서버 담당: `git switch main`, `git pull --ff-only`, `git switch -c feat/poker-server` 후 별도 PR.
- 최초 공유 스냅샷 이후에는 main 직접 push 대신 PR로 검토·병합합니다. 다른 사람의 브랜치를 덮어쓰지 않습니다.
- UI 담당 파일: `projects/react/room.html`, `src/poker/RoomApp.js`, `src/poker/room-main.js`, `src/poker/roomLogic.js`, `src/styles/room.css`(모두 projects/react 아래).
- API·이벤트·필드 계약은 [UI_HANDOFF.md 5~8절](UI_HANDOFF.md)에 있습니다. 계약 변경은 서버 담당과 PR에서 합의하고 테스트와 문서를 함께 갱신합니다. `src/core/`의 공개 인터페이스는 유지합니다.

```powershell
git push -u origin feat/poker-ui
# GitHub에서 base: main, compare: feat/poker-ui로 PR 생성
```

## 검증

각 명령은 저장소 루트에서 실행합니다.

```powershell
Push-Location projects/poker_demo; python -B -m unittest discover -s tests -v; Pop-Location
Push-Location projects/dbms; python -B -m unittest discover -s tests -v; Pop-Location
Push-Location projects/redis; python -B -m unittest discover -s tests -v; Pop-Location
node projects/react/tests/room-logic.test.js
```

이번 공유본 직접 실행 결과는 [VALIDATION.md](VALIDATION.md)에 기록합니다. 과거 인계 문서의 Linux 테스트 및 72항목 브라우저 검증은 이전 보고이며 이번 실행 결과와 구분합니다.

**대기/미검증**: 실제 서로 다른 두 컴퓨터 LAN 플레이, 인터넷 배포, Windows Python 3.14. 공개 인터넷 서비스용 인증·HTTPS·요청 제한은 준비되지 않았습니다. 진행 중 핸드는 서버 재시작 시 복구하지 않으며 마지막 저장 확인된 핸드까지만 복구합니다.

## 출처

기존 과제 저장소에서 분리한 private 협업용 스냅샷입니다. 원본 저작자·설명은 보존했습니다. [SOURCE_PROVENANCE.md](SOURCE_PROVENANCE.md)와 각 프로젝트 문서를 참고하세요. 실행 DB·캐시·로그·인증 정보는 포함하지 않습니다. 테스트의 고정 토큰과 닉네임은 합성 fixture입니다.

현재 알려진 UI 문제: Chrome 기본 headless 창에서 연습 모드 Poker UI 테스트가 7/9 통과했습니다. Inspector 높이 증가와 HUD 겹침 검사 2개가 실패했으며 후속 UI PR에서 확인해야 합니다. 상세 결과는 VALIDATION.md에 있습니다.
