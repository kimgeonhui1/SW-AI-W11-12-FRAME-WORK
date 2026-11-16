# 소스 출처

- 원본: https://github.com/kimgeonhui1/SW-AI-W11-12-FRAME-WORK
- 원본 HEAD: `57f2a3f64233f7d3ff4942d237f9f5961a788a6c`
- 2026-11-16 실제 poker-integration Git worktree의 미커밋 멀티플레이·DBMS·Redis benchmark·UI 및 인계 문서를 함께 복사했습니다. 테스트용 VM 사본에서 가져오지 않았습니다.
- Mini React·Mini Redis의 기존 커밋 작성자에는 `Kim geonhui`가 기록되어 있습니다. 원본 프로젝트 README, 코드 주석 및 그림을 보존했습니다. 새 저장소의 초기 커밋 작성자가 모든 코드의 원저작자라는 뜻은 아닙니다.
- 원본 루트 README는 `docs/UPSTREAM_README.md`에 보존합니다.
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
