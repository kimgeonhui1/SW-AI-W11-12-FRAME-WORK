# 공유본 검증 — 2026-11-16

실제 poker-integration worktree에서 별도 공유 폴더로 복사한 파일을 직접 실행했습니다. VM 테스트 사본이 아니며 원본 작업 폴더의 파일은 수정하지 않았습니다. 서버 Python은 Windows 3.13.7, 화면 로직은 Node.js 24.16.0, 브라우저는 Windows Chrome headless입니다.

| 이번 직접 검사 | 결과 |
|---|---|
| Poker 서버 unittest | 71/71 통과, 188.958초 (멀티플레이·장애 주입·재시작·정산 포함) |
| Mini DBMS unittest | 17/17 통과 (HTTP 동시성·backlog 수정 포함) |
| Mini Redis unittest | 87/87 통과 (benchmark 테스트 포함) |
| Mini React 브라우저 테스트 | 276/276 통과: vdom 39, diff 56, history 6, hooks 37, htmlText 7, ported 106, yut 25 |
| 방 화면 순수 로직 | Node.js 및 Chrome 각각 7/7 통과 |
| 연습 모드 Poker UI | Chrome 기본 headless 창에서 7/9 통과, 2개 실패 |

Poker UI 실패는 `200개 trace가 페이지나 Inspector 높이를 늘리지 않음`의 `inspector grew`, `가로 넘침 없이 모바일 조작부와 HUD 배치`의 `HUD overlaps board`입니다. 다른 화면 크기나 실제 기기까지 검증한 결과는 아닙니다. 이번 공유 준비에서는 UI 스타일을 수정하지 않았으며 후속 UI PR에서 재현·수정해야 합니다.

초기 샌드박스 실행은 로컬 소켓 연결이 WinError 10013으로 차단되었습니다. 위 서버 결과는 소켓 연결이 허용된 환경에서 재실행한 결과입니다. Edge headless는 테스트 DOM을 반환하지 않아 성공으로 집계하지 않았고 Chrome으로 검증했습니다.

## 이전 보고와 미검증 범위

UI_HANDOFF.md의 Linux Poker 71개, DBMS 반복 실행, Redis 87개 및 독립 브라우저 두 세션 72항목은 **이전 보고**입니다. 이번에 그 브라우저 E2E 시나리오를 재실행한 것은 아닙니다.

- 실제 두 컴퓨터 LAN 연결·플레이: **대기**.
- Windows Python 3.14, 인터넷 배포: 미검증.
- 백만 행 DBMS benchmark 및 성능 수치: 이번에 재실행하지 않음.
- 기존 프로젝트 README의 테스트·성능 배지는 원본 설명이며 이번 전체 검증을 뜻하지 않음.
- 테스트는 임시 DB와 합성 게스트를 사용하며 실행 데이터는 저장소에 포함하지 않음.
