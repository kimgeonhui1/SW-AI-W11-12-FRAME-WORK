# [rwlock.py] 읽기-쓰기 락 (Phase 3) — SELECT끼리는 동시에, INSERT는 혼자
#
# ■ 왜 락 하나(Lock)가 아닌가: 락 하나면 SELECT끼리도 줄을 선다. 읽기는 서로 데이터를 바꾸지 않으므로 같이 해도 안전하다
#
#   지금 상태 \ 새 요청 | 읽기(SELECT)   | 쓰기(INSERT)
#   아무도 없음          | 통과           | 통과
#   읽는 중              | 통과(같이 읽음) | 대기
#   쓰는 중              | 대기           | 대기
#
# ■ 쓰기 굶주림 방지: 읽기가 끝없이 이어지면 쓰기가 영원히 기다린다 → 쓰기가 기다리는 중이면 새 읽기도 기다리게 한다(쓰기 우선)
#
# ■ 만드는 법 (Pintos 동기화 과제와 같음): 락 하나 + 조건 변수 하나(threading.Condition)
#   상태(읽는 수, 쓰는 중인가, 기다리는 쓰기 수)는 반드시 락을 잡고 바꾸고, 조건이 안 맞으면 wait()로 잠든다.
#   상태가 바뀌면 notify_all()로 깨워 각자 조건을 다시 확인하게 한다 (while로 다시 확인: 깨어났다고 조건이 맞는다는 보장은 없다)

import threading
from contextlib import contextmanager


class RWLock:
    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0  # 지금 읽는 스레드 수
        self._writing = False  # 지금 쓰는 스레드가 있는가 (최대 1개)
        self._waiting_writers = 0  # 쓰려고 기다리는 스레드 수

    @contextmanager
    def read(self):
        with self._cond:
            while self._writing or self._waiting_writers:  # 쓰는 중이거나 쓰기가 기다리면 양보한다
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()  # 마지막 읽기가 끝났다 → 기다리던 쓰기를 깨운다

    @contextmanager
    def write(self):
        with self._cond:
            self._waiting_writers += 1
            try:
                while self._writing or self._readers:
                    self._cond.wait()
            finally:
                self._waiting_writers -= 1  # 기다리다 예외(Ctrl+C 등)가 나도 수를 되돌려, 읽기가 영원히 막히지 않게
            self._writing = True
        try:
            yield
        finally:
            with self._cond:
                self._writing = False
                self._cond.notify_all()  # 기다리던 읽기 · 쓰기를 모두 깨운다 (누가 먼저 들어갈지는 조건이 정한다)
