# 소스 출처

- 원본: https://github.com/kimgeonhui1/SW-AI-W11-12-FRAME-WORK
- 원본 HEAD: `57f2a3f64233f7d3ff4942d237f9f5961a788a6c`
- 2026-11-16 실제 poker-integration Git worktree의 미커밋 멀티플레이·DBMS·Redis benchmark·UI 및 인계 문서를 함께 복사했습니다. 테스트용 VM 사본에서 가져오지 않았습니다.
- Mini React·Mini Redis의 기존 커밋 작성자에는 `Kim geonhui`가 기록되어 있습니다. 원본 프로젝트 README, 코드 주석 및 그림을 보존했습니다. 새 저장소의 초기 커밋 작성자가 모든 코드의 원저작자라는 뜻은 아닙니다.
- 원본 루트 README는 팀 저장소의 `README.md` 그대로입니다. 포커 README는 `POKER_README.md`입니다. 포커 문서에 나오는 "README"는 `POKER_README.md`를 가리킵니다.
- 원본에서 별도 LICENSE/NOTICE 파일은 발견하지 못했습니다. 새 라이선스를 임의로 부여하지 않습니다. 외부 재배포 전 원저작자와 사용 조건을 확인해야 합니다.
- 이번 공유 준비에서는 실행 소스의 동작을 변경하지 않았습니다. README·인계 문서·검증/출처 문서·제외 규칙만 정리했습니다.

## 이후 변경 (2026-11-16, `feat/poker-ui`)

방 대전 화면(`room.html`)의 테이블을 CSS 3D로 바꿨습니다. 이 변경은 위 공유 준비 이후의 것이며 실행 소스의 화면 동작을 바꿉니다. 서버·엔진·DBMS·Redis·Mini React 코어(`src/core/`)·연습 모드(`poker.html`)는 바꾸지 않았습니다. 상세 내용과 검증 결과는 `docs/3D/3D_UI_PLAN.md` 15절(코드별 설명은 `docs/3D/ROOM_3D_CHANGES.md`)에 있습니다.

- 원본 코드 중 수정한 파일 (모두 README의 UI 담당 파일 범위 안):
  - `projects/react/src/poker/RoomApp.js` (테이블을 3D 평면 구조로, 3D 카드·칩, 딜러 버튼, 2D/3D·빛 번짐 토글)
  - `projects/react/src/poker/roomLogic.js` (보기 설정 저장·읽기 함수)
  - `projects/react/src/styles/room.css` (테이블 부분을 CSS 3D로 다시 작성)
  - `projects/react/room.html` (캐시 버전만)
  - `projects/react/tests/room-logic.test.js` (보기 설정 테스트 1개 추가)
- 새로 만든 파일: `docs/3D/` 폴더의 문서 3개 (`3D_UI_PLAN.md`, `POKER_DEMO_REPORT.md`, `ROOM_3D_CHANGES.md`)
- 외부 라이브러리·제3자 코드는 추가하지 않았습니다. 처음에 three.js로 만들었던 버전은 저장소에 넣지 않고 되돌렸습니다.
- 위 원본 코드의 원저작자 표기와 "외부 재배포 전 사용 조건 확인" 원칙은 이 변경 이후에도 그대로 적용됩니다.

## 팀 저장소로 가져오기 (2026-11-18, `feat/poker-integration`)

`a01030704572-bit/jungle-poker-lab`의 `feat/poker-multiway`(c6f907d, 김준우 님의 `feat/poker-ui` 2a2108c 포함)를 팀 저장소 `dev`(57f2a3f) 위로 옮겼습니다.

- 원본 커밋 9개를 같은 순서·작성자·작성 시각·메시지로 다시 만들었습니다. 각 커밋 메시지 끝에 원본 커밋 번호가 있습니다. 김준우 님 커밋 3개(a294feb, 6e117d0, 2a2108c)는 작성자 molru-1 그대로입니다.
- 원본 첫 커밋(2d2aff0)은 팀 `dev`를 복사한 스냅샷이었습니다. 그래서 팀 파일 55개는 줄 끝(CRLF/LF)만 달랐는데, 이 파일들은 `dev`의 파일을 그대로 두었습니다. 내용 차이는 없습니다.
- 팀 `dev`에서 지운 파일은 없습니다. 내용이 바뀐 팀 파일은 `projects/redis/demo/benchmark.py` 하나입니다(포커 작업 때 측정 방식을 고친 버전).
- 루트 `README.md`는 팀 README를 유지하고 끝에 포커 안내만 덧붙였습니다. 원본의 루트 README는 `POKER_README.md`로 옮겼고, 팀 README 사본이던 `docs/UPSTREAM_README.md`는 넣지 않았습니다.
- 코드 동작은 바꾸지 않았습니다. Redis는 포커가 쓰던 버전(dev 시점) 그대로이고, `feat/Kimgeonhui-Redis`의 이후 변경은 합치지 않았습니다.

### 최신 원본 동기화 (2026-11-18)

- 원본 `feat/poker-multiway`의 `c5c589032a3fe2a45d1682abc13066b6858eadea`를 `078ca8482f735a36f1bb508f9f2b034a7821342a`로 cherry-pick했습니다. 작성자 molru-1과 작성 시각을 보존했고 커밋 메시지에 원본 SHA가 있습니다.
- 반영 파일: `projects/react/src/poker/RoomApp.js`, `projects/react/src/styles/room.css`, `projects/react/room.html`, `docs/3D/ROOM_3D_CHANGES.md`. 3~4인 화면의 이름표·카드·배지 배치와 CSS 캐시 버전 변경입니다.
- 원본 최신 커밋과 실행 파일 내용은 줄 끝(CRLF/LF)을 정규화하면 동일합니다. 기존 README 배치 및 이 출처 문서의 차이는 유지합니다.
- Redis·DBMS·Mini React 코어는 이번 동기화에서 교체하지 않았습니다. 기존 로컬 저장소와 다른 worktree의 미커밋 변경도 가져오지 않았습니다.
- 이 항목은 최신 원본 동기화 기록이며, 별도 팀원 구현의 채택을 뜻하지 않습니다.
