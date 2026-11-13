# [store.py] Mini Redis 본체 — 해시 테이블 위에 저장/조회/삭제 + 만료(TTL) + 동시성 제어
#
# 설계 문서: projects/redis/Docs/설계.md  2-2 · 3-2 · 5 · 6 · 7장
#
# ■ 계층에서의 위치: Command Layer
#   아래 hashtable.py(키 → 값)를 쓰고, 위 server.py(HTTP)는 모른다.
#   Redis 규칙(만료 · ttl 의 -1 / -2 · SET 이 만료를 지움)과 동시성 제어는 모두 이 파일이 맡는다.
#
# ■ 데이터는 해시 테이블 두 개에 나눠 둔다 (dev 와 같은 구조)
#   _data    : 키 → 값                 "user:1" → "Nameisme"
#   _expires : 키 → 만료 시각 (TTL을 준 키만)  "hi" → 12345.67  (clock() 이 12345.67 이 되는 순간 만료)
#   - 실제 Redis 도 값과 만료 시각을 따로 저장한다.
#   - 만료가 있는 키만 _expires 에 있으므로, sweep() 은 만료 키만 훑으면 된다 (전체 키를 훑지 않는다).
#
# ■ 시계: clock 매개변수 (기본 time.monotonic)
#   monotonic 은 컴퓨터 시계를 바꿔도(NTP 보정 · 수동 변경) 뒤로 가지 않아 만료가 꼬이지 않는다.
#   테스트는 가짜 시계를 넣어 실제로 기다리지 않고 시간을 흘린다.
#
# ■ 만료 처리 — 두 방법을 함께 쓴다 (실제 Redis 와 같음)
#   1) 지연 삭제: 키를 볼 때마다(_alive) 만료됐으면 그 자리에서 지우고 "없음" → 만료된 값은 절대 응답으로 나가지 않는다
#   2) 주기 삭제: sweep() — 아무도 다시 읽지 않는 만료 키도 메모리에서 치운다 (서버가 1초마다 부른다)
#
# ■ 동시성: threading.Lock 하나. 모든 공개 메서드는 락 안에서만 해시 테이블을 만진다
#   HTTP 서버는 요청마다 스레드가 따로 돌고, sweep 스레드도 동시에 돈다.
#   "만료 확인 → 삭제", "키 있음? → 갱신 / 없음 → 삽입 + 리사이즈", "키 있음? → 만료 설정" 은
#   확인과 쓰기 사이에 다른 스레드가 끼면 틀린 결과가 나온다 → 락으로 "한 번에 명령 하나"만 실행되게 한다.
#   명령 하나는 평균 O(1) 이라 HTTP 처리 시간에 비해 줄 서는 시간은 무시할 수 있다.
#   shortcut: 락 하나가 병목이 되면(초당 수만 요청) 칸 범위별로 락을 나눈다

import math
import threading
import time

from .hashtable import HashTable

# 가장 짧은 ttl = 1ms (실제 Redis 의 PEXPIRE 도 1ms 단위). dev 와 같은 규칙.
# 이보다 작으면 "지금 시각 + ttl" 이 부동소수점에서 지금 시각과 같아져(1000.0 + 1e-14 == 1000.0) 저장하자마자 만료된다
MIN_TTL = 0.001


class MiniRedis:
    # 해시 테이블 두 개 + 락 준비
    # clock: 지금 시각(초)을 돌려주는 함수. 테스트에서 가짜 시계를 넣는다 (dev 와 같은 매개변수)
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._data = HashTable()  #    키 → 값
        self._expires = HashTable()  # 키 → 만료 시각 (ttl 을 준 키만)
        self._lock = threading.Lock()

    # 값 저장. ttl(초)을 주면 그 시간 뒤 만료
    # ttl 없이 덮어쓰면 기존 만료는 사라진다 (실제 Redis SET 규칙)
    def set(self, key, value, ttl=None):
        if ttl is not None:
            _check_ttl(ttl)  # 락 밖에서 먼저 검사 → 틀린 ttl 이면 아무것도 바꾸지 않고 ValueError
        with self._lock:
            self._data.set(key, value)
            if ttl is None:
                self._expires.delete(key)
            else:
                self._expires.set(key, self._clock() + ttl)
            return True

    # 값 조회. 없거나 만료됐으면 None (만료된 값은 절대 돌려주지 않음)
    # 값으로 None 을 저장한 경우와 "없음" 은 exists 로 구별한다
    def get(self, key):
        with self._lock:
            return self._data.get(key) if self._alive(key) else None

    # 값과 남은 만료 시간을 "한 번에" 조회 → (값, ttl). 없거나 만료됐으면 (None, -2)
    # get 과 ttl 을 따로 부르면 그 사이에 다른 요청이 끼어 "값은 있는데 ttl 은 -2" 같은 어긋난 조합이 나온다 (서버 GET 이 사용)
    def get_with_ttl(self, key):
        with self._lock:
            if not self._alive(key):
                return None, -2
            return self._data.get(key), self._ttl_left(key)

    # 삭제(무효화). 지웠으면 True (이미 만료된 키는 없는 것 → False)
    def delete(self, key):
        with self._lock:
            if not self._alive(key):
                return False
            self._expires.delete(key)
            return self._data.delete(key)

    # 키가 있는지 (만료된 키는 없는 것)
    def exists(self, key):
        with self._lock:
            return self._alive(key)

    # 있는 키에 만료 시간(초) 설정. 키가 없으면 False
    def expire(self, key, ttl):
        _check_ttl(ttl)
        with self._lock:
            if not self._alive(key):
                return False
            self._expires.set(key, self._clock() + ttl)
            return True

    # 남은 만료 시간(초). 만료 없음 = -1, 키 없음 = -2 (실제 Redis 규칙)
    def ttl(self, key):
        with self._lock:
            return self._ttl_left(key) if self._alive(key) else -2

    # 만료된 키를 메모리에서 정리하고 지운 개수 반환 (서버가 주기적으로 호출)
    # shortcut: 만료 키를 전부 훑는다(O(만료 키 수)). 수십만 개가 되면 실제 Redis 처럼 무작위 20개 표본 검사로 바꾼다
    def sweep(self):
        with self._lock:
            now = self._clock()  # 한 번만 읽어 같은 기준 시각으로 판단한다
            removed = 0
            for key in self._expires.keys():  # keys() 는 복사본이라 돌면서 지워도 안전
                if self._expires.get(key) <= now:
                    self._remove(key)
                    removed += 1
            return removed

    # 스냅샷용: 만료되지 않은 모든 키 → [(키, 값, 남은 초 또는 None)] (persistence.save_snapshot 이 사용, 김건희 님 브랜치와 같음)
    # 락 하나 안에서 한 번에 찍어서, 저장 도중 다른 요청이 끼어들어도 "한 시점의 사진" 이 된다.
    # 남은 초는 올림하지 않은 그대로 (복구할 때 꺼져 있던 시간을 정확히 빼려고)
    def dump(self):
        with self._lock:
            now = self._clock()
            entries = []
            for key in self._data.keys():
                expire_at = self._expires.get(key)
                if expire_at is not None and expire_at <= now:
                    continue  # 이미 만료된 키는 저장하지 않는다 (지우지는 않음 — 읽기 전용)
                entries.append((key, self._data.get(key), None if expire_at is None else expire_at - now))
            return entries

    # 저장된 키 수 (아직 sweep 되지 않은 만료 키도 포함) — 서버의 GET /health 가 사용
    def __len__(self):
        with self._lock:
            return len(self._data)

    # ── 내부 (락을 잡은 상태에서만 부른다) ─────────────────────────────

    # 지연 삭제: 키가 살아 있으면 True. 없거나 만료됐으면 False (만료된 것은 이때 지운다)
    # 만료 시각과 "같은" 순간도 만료로 본다 (<=): ttl=1 로 저장하고 정확히 1초 뒤에는 이미 없어야 한다
    def _alive(self, key):
        if key not in self._data:
            return False
        expire_at = self._expires.get(key)
        if expire_at is not None and expire_at <= self._clock():
            self._remove(key)
            return False
        return True

    # 살아 있는 키의 남은 초. 만료 없음 = -1
    # 올림(ceil): 0.3초 남은 키도 살아 있으므로 1. 내림이면 살아 있는 키가 0 이 되어 헷갈린다
    def _ttl_left(self, key):
        expire_at = self._expires.get(key)
        return -1 if expire_at is None else math.ceil(expire_at - self._clock())

    def _remove(self, key):
        self._data.delete(key)
        self._expires.delete(key)


# ttl 은 MIN_TTL 이상의 유한한 숫자(초)만 받는다 — 정수 · 소수 모두 (dev 와 같은 규칙).
# 0 · 음수 · NaN · Infinity · 문자열 · None → ValueError (서버가 400 으로 바꾼다).
# True 는 파이썬에서 int 의 한 종류(= 1)라 따로 막는다 — 그냥 두면 1초 ttl 로 들어간다
def _check_ttl(ttl):
    valid = not isinstance(ttl, bool) and isinstance(ttl, (int, float))
    try:
        valid = valid and math.isfinite(ttl) and ttl >= MIN_TTL
    except OverflowError:  # 9999...(수백 자리) 같은 너무 큰 정수는 float 로 못 바꿔 isfinite 가 OverflowError 를 낸다
        valid = False
    if not valid:
        raise ValueError(f"ttl은 {MIN_TTL}초 이상의 유한한 숫자여야 합니다")
