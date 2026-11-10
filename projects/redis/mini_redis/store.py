# [store.py] Mini Redis 본체 — 해시 테이블 위에 저장/조회/삭제 + 만료(TTL) + 동시성 제어
#
# ■ 데이터는 해시 테이블 두 개에 나눠 둔다
#   _data    : 키 → 값
#   _expires : 키 → 만료 시각 (TTL을 준 키만). 실제 Redis도 값과 만료 시각을 따로 저장한다
#
# ■ 만료 처리 (실제 Redis와 같은 두 가지 방식)
#   1) 지연 삭제(lazy): 키를 읽을 때 만료됐으면 그 자리에서 지우고 "없음"으로 응답한다 → 만료된 값은 절대 응답으로 나가지 않는다
#   2) 주기 삭제(active): 아무도 읽지 않는 만료 키도 메모리에서 치우도록 서버가 주기적으로 sweep()을 부른다
#
# ■ 동시성: 모든 명령을 하나의 락(Lock) 안에서 실행한다
#   HTTP 서버는 요청마다 스레드를 쓰므로, 두 요청이 같은 해시 테이블을 동시에 고치면(예: 리사이즈 중에 set) 구조가 깨진다.
#   락으로 "한 번에 명령 하나"만 실행되게 한다. 실제 Redis가 명령을 한 스레드에서 하나씩 처리하는 것과 같은 효과다.
#   명령 하나는 아주 짧아서(평균 O(1)) 줄을 서도 대기 시간이 작다.

import math
import threading
import time

from .hashtable import HashTable


class MiniRedis:
    # clock: 지금 시각(초)을 돌려주는 함수. 테스트에서 가짜 시계를 넣어 실제로 기다리지 않고 시간을 흘린다
    #        monotonic은 컴퓨터 시계를 바꿔도 뒤로 가지 않는 시계라서 만료 계산이 꼬이지 않는다
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._data = HashTable()
        self._expires = HashTable()
        self._lock = threading.Lock()

    # 값 저장. ttl(초)을 주면 그 시간 뒤 만료. 실제 Redis처럼 SET은 이전 TTL을 지운다
    def set(self, key, value, ttl=None):
        if ttl is not None:
            _check_ttl(ttl)
        with self._lock:
            self._data.set(key, value)
            if ttl is None:
                self._expires.delete(key)
            else:
                self._expires.set(key, self._clock() + ttl)

    # 값 조회. 없거나 만료됐으면 None (만료된 값은 절대 돌려주지 않음)
    # 값으로 None을 저장한 경우와 "없음"을 구분하려면 exists를 쓴다
    def get(self, key):
        with self._lock:
            if self._expire_if_needed(key):
                return None
            return self._data.get(key)

    # 삭제(무효화). 지웠으면 True (이미 만료된 키는 없는 것으로 본다)
    def delete(self, key):
        with self._lock:
            if self._expire_if_needed(key):
                return False
            self._expires.delete(key)
            return self._data.delete(key)

    # 키가 있는지 (만료된 키는 없는 것)
    def exists(self, key):
        with self._lock:
            return not self._expire_if_needed(key) and key in self._data

    # 있는 키에 만료 시간(초) 설정. 키가 없으면 False
    def expire(self, key, ttl):
        _check_ttl(ttl)
        with self._lock:
            if self._expire_if_needed(key) or key not in self._data:
                return False
            self._expires.set(key, self._clock() + ttl)
            return True

    # 남은 만료 시간(초, 올림). 만료 없음 = -1, 키 없음 = -2 (실제 Redis 규칙)
    def ttl(self, key):
        with self._lock:
            if self._expire_if_needed(key) or key not in self._data:
                return -2
            expire_at = self._expires.get(key)
            if expire_at is None:
                return -1
            return math.ceil(expire_at - self._clock())

    # 만료된 키를 메모리에서 정리하고 지운 개수 반환 (서버가 주기적으로 호출)
    def sweep(self):
        # shortcut: 만료 키를 전부 훑는다(O(만료 키 수)). 키가 수십만 개가 되면 실제 Redis처럼 일부만 무작위로 뽑아 검사하도록 바꿔야 한다
        with self._lock:
            now = self._clock()
            removed = 0
            for key in self._expires.keys():
                if self._expires.get(key) <= now:
                    self._remove(key)
                    removed += 1
            return removed

    # 저장된 키 수 (아직 sweep되지 않은 만료 키도 포함)
    def __len__(self):
        with self._lock:
            return len(self._data)

    # ── 내부 (락을 잡은 상태에서만 부른다) ──

    # 지연 삭제: 만료됐으면 지우고 True
    def _expire_if_needed(self, key):
        expire_at = self._expires.get(key)
        if expire_at is not None and expire_at <= self._clock():
            self._remove(key)
            return True
        return False

    def _remove(self, key):
        self._data.delete(key)
        self._expires.delete(key)


# 가장 짧은 ttl = 1ms (실제 Redis의 PEXPIRE도 1ms 단위).
# 이보다 작으면 "지금 시각 + ttl"이 부동소수점에서 지금 시각과 같아져(1000.0 + 1e-14 == 1000.0) 저장하자마자 만료된다
MIN_TTL = 0.001


# ttl은 MIN_TTL 이상의 유한한 숫자(초)만 허용. bool은 int의 하위 타입이라 True가 1초로 들어오는 것을 따로 막는다
def _check_ttl(ttl):
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl < MIN_TTL:
        raise ValueError(f"ttl은 {MIN_TTL}초 이상의 숫자여야 합니다")
