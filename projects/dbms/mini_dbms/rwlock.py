# [rwlock.py] 읽기-쓰기 락 — 읽기(SELECT)는 여럿이 동시에, 쓰기(INSERT)는 혼자
#
#   읽기만 있을 때:   R1 ████   R2 ████   R3 ████        ← 겹쳐서 동시에
#   쓰기가 오면:      R1 ██ │ W ████ │ R2 ███            ← 쓰기는 혼자, 앞뒤 읽기와 겹치지 않음
#
# ■ 왜 필요한가: 쓰기는 "id 정하기 → 파일에 붙이기 → B+ 트리에 넣기(노드 분할)" 를 한 번에 해야 하고,
#   읽기가 그 도중의 트리(분할 중인 노드)를 보면 키를 놓칠 수 있다. 그런데 읽기끼리는 서로를 망가뜨리지 않는다.
#   Lock 하나로 모두 줄 세우면 SELECT 끼리도 기다리게 된다 → 읽기는 함께, 쓰기만 따로.
#
# ■ 쓰기 우선: 쓰기가 기다리는 중이면 새 읽기는 들어오지 못한다.
#   그렇지 않으면 읽기가 끊임없이 이어질 때 쓰기가 영원히 못 들어간다(굶주림, starvation).
#
# ■ 표준 라이브러리에 없어서 Condition(락 + 기다리기 · 깨우기) 으로 만든다.
# ■ 다시 들어가기(재진입)는 안 된다: 읽기 락을 쥔 채로 같은 락을 또 잡으면, 그 사이 쓰기가 기다리고 있으면 영원히 멈춘다.
#   엔진은 문장 하나에 락을 한 번만 잡는다.

import threading
from contextlib import contextmanager


class RWLock:
    def __init__(self):
        self._cond = threading.Condition()
        self._readers = 0  # 지금 읽는 중인 수
        self._writer = False  # 지금 쓰는 중인가
        self._waiting_writers = 0  # 쓰려고 기다리는 수 (있으면 새 읽기를 막는다)

    @contextmanager
    def read(self):
        with self._cond:
            while self._writer or self._waiting_writers:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()  # 기다리던 쓰기를 깨운다

    @contextmanager
    def write(self):
        with self._cond:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers:
                    self._cond.wait()
            finally:
                self._waiting_writers -= 1
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()  # 기다리던 읽기 · 쓰기를 모두 깨운다
