# Mini Redis

해시 테이블을 직접 만들어(파이썬 `dict` 사용 X) 그 위에 **키-값 저장 · 만료(TTL) · 동시성 제어 · HTTP JSON API** 를 올린 작은 Redis 입니다.
느린 API 앞에 캐시로 붙여 성능이 얼마나 좋아지는지도 보여 줍니다.

- 언어: Python 3.10 이상, **표준 라이브러리만** (설치할 것 없음) · Python 3.14.7 · macOS 에서 검증
- 브랜치: `feat/Kimjunwoo-Redis` (김준우)
- 테스트: 제 테스트 **75개** + 팀원(dev) 테스트 **61개** 모두 통과
- 성능: 같은 요청 20번 평균 **204.58ms → 11.32ms (약 18배)**

| 문서 | 내용 |
|---|---|
| [README.md](./README.md) | 이 문서 — 무엇이고, 어떻게 실행하고, 어떻게 쓰는지 |
| [설계.md](./설계.md) | 계층 구조 · 자료구조 · 함수 · 흐름 · API 규격 · 결정과 이유 |
| [보고서.md](./보고서.md) | 구현 결과 · 테스트 · 성능 · dev 와 맞춘 것 · 검증 결과 |

---

## 1. 빠른 시작

`projects/redis` 폴더에서 실행합니다.

```bash
python -m unittest
```

```bash
python -m mini_redis.server --port 6380
```

```bash
curl -X PUT localhost:6380/keys/user:1 -d '{"value": "Nameisme", "ttl": 60}'
curl localhost:6380/keys/user:1
```

```bash
python -m demo.benchmark
```

- `unittest` — 테스트 75개 (약 7초)
- `mini_redis.server` — Mini Redis 서버. 기본 `127.0.0.1` 이라 같은 컴퓨터에서만 접속됩니다 (`--host 0.0.0.0` 이면 외부 허용)
- `demo.benchmark` — 캐시 사용 / 미사용 성능 비교. 서버를 알아서 띄우므로 이 명령 하나면 됩니다

---

## 2. 구조

```
 Client          demo/api_server.py · demo/benchmark.py · curl
   │ HTTP JSON
 API Server      mini_redis/server.py      요청 읽기 · 입력 검사 · JSON 응답 · 1초마다 만료 키 정리
   │ 메서드 호출
 Command Layer   mini_redis/store.py       MiniRedis: 만료(TTL) · 락 · Redis 규칙(-1 / -2)
   │ get / set / delete / keys
 Storage Engine  mini_redis/hashtable.py   HashTable: FNV-1a 64비트 · 체이닝 · 0.75 넘으면 2배
```

아래 계층은 위 계층을 모릅니다 (해시 테이블은 만료를 모르고, 저장소는 HTTP 를 모릅니다). 그래서 계층마다 따로 테스트할 수 있습니다.

```
projects/redis/
├── mini_redis/
│   ├── hashtable.py     해시 테이블 (dict 없이 직접 구현)
│   ├── store.py         MiniRedis 본체 (TTL · 락)
│   ├── server.py        HTTP JSON API 서버
│   └── persistence.py   (선택) 스냅샷 저장 · 복구 — 아직 TODO
├── demo/
│   ├── api_server.py    캐시를 쓰는 예제 API (dev 파일 그대로)
│   └── benchmark.py     캐시 사용 / 미사용 성능 비교
├── tests/               test_hashtable · test_store · test_server · test_demo
└── Docs/                README · 설계 · 보고서
```

---

## 3. HTTP API

요청 · 응답 본문은 모두 JSON 입니다. 키에 `/` · 한글 같은 문자가 있으면 URL 인코딩해서 보냅니다 (예: `메이플/a` → `%EB%A9%94%EC%9D%B4%ED%94%8C%2Fa`).

| 요청 | 하는 일 | 성공 응답 |
|---|---|---|
| `PUT /keys/{key}` body `{"value": 값, "ttl": 초}` | 저장 (`ttl` 은 선택, 소수 가능 · 최소 0.001초) | `200 {"ok": true}` |
| `GET /keys/{key}` | 조회 | `200 {"key": k, "value": v, "ttl": n}` |
| `DELETE /keys/{key}` | 삭제 (캐시 무효화) | `200 {"deleted": true \| false}` |
| `GET /keys/{key}/ttl` | 남은 만료 시간 | `200 {"ttl": 초}` — 만료 없음 `-1`, 키 없음 `-2` |
| `POST /keys/{key}/expire` body `{"ttl": 초}` | 만료 시간 설정 | `200 {"ok": true}` |
| `GET /health` | 상태 확인 | `200 {"keys": 저장된 키 수}` |

**규칙 (실제 Redis 와 같게)**
- 만료된 키는 절대 응답으로 나가지 않습니다 (읽을 때 바로 지움 + 1초마다 정리).
- `ttl` 없이 같은 키에 다시 저장하면 기존 만료가 사라집니다.
- 남은 시간은 올림입니다 (0.3초 남으면 `1`).
- `value` 로 `null` 은 저장할 수 없습니다 ("없음" 과 구별이 안 되므로).

**오류 응답** — 모두 `{"error": "이유"}` 입니다.

| 상태 | 언제 | 예 |
|---|---|---|
| 400 | 잘못된 JSON · `NaN` · 객체가 아닌 본문 · `value` 없음 · 잘못된 ttl 등 | `{"error": "ttl은 0.001초 이상의 유한한 숫자여야 합니다"}` |
| 404 | 키 없음 · 만료됨 / 없는 경로 | `{"error": "키가 없습니다"}` |
| 405 | 경로는 맞는데 메서드가 다름 | `{"error": "GET / PUT / DELETE만 지원합니다"}` |
| 408 | 본문을 10초 안에 다 보내지 않음 | `{"error": "요청 본문을 제한 시간 안에 다 받지 못했습니다"}` |
| 413 | 본문이 1MB 초과 | `{"error": "요청 본문이 너무 큽니다 (최대 1MB)"}` |
| 500 | 예상 못 한 오류 (서버는 계속 동작) | `{"error": "서버 내부 오류"}` |

전체 문구 목록은 [설계.md](./설계.md) 8장에 있습니다.

**예시**

```bash
curl -X PUT localhost:6380/keys/session:42 -d '{"value": {"user": "철수"}, "ttl": 1.5}'
curl localhost:6380/keys/session:42/ttl
curl -X POST localhost:6380/keys/session:42/expire -d '{"ttl": 30}'
curl -X DELETE localhost:6380/keys/session:42
curl localhost:6380/health
```

---

## 4. 파이썬에서 바로 쓰기

HTTP 없이 저장소만 쓸 수도 있습니다.

```python
from mini_redis.store import MiniRedis

r = MiniRedis()
r.set("user:1", {"name": "철수"}, ttl=60)
r.get("user:1")           # {'name': '철수'}
r.ttl("user:1")           # 60
r.get_with_ttl("user:1")  # ({'name': '철수'}, 60) — 값과 ttl 을 한 번에
r.delete("user:1")        # True
r.ttl("user:1")           # -2 (키 없음)
```

여러 스레드에서 동시에 써도 안전합니다 (내부 락 하나). 테스트에서는 `MiniRedis(clock=가짜_시계)` 로 시간을 기다리지 않고 흘릴 수 있습니다.

---

## 5. 캐시 데모

느린 원본(0.2초 걸리는 DB 흉내) 앞에 Mini Redis 를 캐시로 붙인 예제 API 입니다.

```bash
python -m mini_redis.server --port 6380
```

```bash
python -m demo.api_server --port 8000 --redis http://127.0.0.1:6380
```

```bash
curl localhost:8000/items/1
```

| 요청 | 결과 |
|---|---|
| `GET /items/1` 처음 | `"cache": "MISS"` — 원본을 읽고(0.2초) 캐시에 60초 저장 |
| `GET /items/1` 다시 | `"cache": "HIT"` — 캐시에서 바로 (수 ms) |
| `GET /items/1?cache=off` | `"cache": "OFF"` — 매번 원본 |
| `PUT /items/1` body `{"price": 5}` | 원본 수정 + 버전을 올려 옛 캐시를 무효화 |
| Mini Redis 가 꺼져 있을 때 | `"cache": "BYPASS"` — 원본으로라도 응답 |

**버전 키로 무효화하는 이유**: 캐시 키가 `item:{id}:v{버전}` 입니다. "수정한 뒤 캐시 삭제" 만 하면, 느린 읽기 도중에 수정이 끼었을 때 그 읽기가 옛 값을 늦게 저장해 최대 60초 동안 옛 값이 보입니다. 버전 키면 옛 값은 옛 키로만 가고 새 요청은 새 키만 읽습니다.

**성능** (`python -m demo.benchmark`, 같은 아이템 20번):

| 방식 | 평균 응답 시간 |
|---|---|
| 캐시 미사용 | 204.58ms |
| 캐시 사용 (첫 요청 MISS 포함) | 11.32ms |

---

## 6. 테스트

```bash
python -m unittest
```

| 파일 | 개수 | 주로 확인하는 것 |
|---|---|---|
| `tests/test_hashtable.py` | 20 | 충돌 · 리사이즈 경계 · dict 와 무작위 2,000번 대조 · 한글 / 반쪽 문자 키 |
| `tests/test_store.py` | 23 | ttl 규칙(-1 / -2 · 올림 · 경계) · 지연 / 주기 삭제 · 잘못된 ttl · 스레드 동시 쓰기 |
| `tests/test_server.py` | 22 | 모든 경로 · 상태 코드 · 오류 문구 · 413 · 408 · 클라이언트 50개 동시 접속 · 실제 1초 주기 정리 |
| `tests/test_demo.py` | 10 | MISS → HIT · 버전 키 무효화 · 느린 읽기 중 수정 · Mini Redis 장애 시 BYPASS |

시간이 걸리는 테스트는 가짜 시계로 기다리지 않습니다. 팀원(dev) 테스트 61개도 이 코드에서 그대로 통과합니다 ([보고서.md](./보고서.md) 4 · 9장).

---

## 7. 팀 규칙과 dev

- 팀 뼈대(`25c050c`)의 파일 · 함수 이름 23개를 그대로 지켰습니다. 매개변수는 `MiniRedis(clock=...)` 선택 매개변수 하나만 더했습니다 (dev 와 같음).
- 처음에는 제 설계대로 만든 뒤, 해시 비트 수 · 저장 구조 · ttl 규칙 · API · 무효화 방식 · 오류 문구까지 dev(김건희 님 구현)와 동작을 맞췄습니다. `demo/api_server.py` 는 dev 파일을 그대로 씁니다.
- 자세한 비교는 [보고서.md](./보고서.md) 4장에 있습니다.

---

## 8. 한계

| 한계 | 설명 |
|---|---|
| 자료형 | 문자열 키 → JSON 값 하나만. Redis 의 List · Set · Hash 등은 없음 |
| 프로토콜 | Redis 의 RESP 가 아니라 HTTP JSON |
| 영속성 | 아직 없음 — 서버를 끄면 데이터가 사라짐 (`persistence.py` TODO) |
| 메모리 | 한도 · LRU 제거 없음. 해시 테이블은 커지기만 하고 줄지 않음 |
| 규모 | 락 하나 · 1초마다 만료 키 전부 훑기 — 초당 수만 요청 · 만료 키 수십만 개를 넘으면 바꿔야 함 (`shortcut:` 주석) |
| 데모 서버 | `demo/api_server.py`(dev 파일)는 클라이언트 수십 개가 한꺼번에 접속하면 일부 연결이 끊김. Mini Redis 서버는 고쳤음 ([보고서.md](./보고서.md) 9장) |
