# [threadpool.py] 스레드 풀 (Phase 3) — 작업자 스레드를 미리 N개 만들어 두고, 작업 큐에서 일을 꺼내 처리한다
#
#   요청 ──submit──▶ [ 작업 큐 (최대 queue_size개) ] ──get──▶ 작업자 1, 2, ... N (각자 반복: 꺼내기 → 실행)
#
# ■ 요청마다 스레드를 새로 만들지 않는 이유
#   - 스레드를 만들고 없애는 비용이 없다 (이 PC에서 하나에 약 0.37ms)
#   - 동시에 도는 스레드가 N개로 고정된다 → 요청이 몰려도 스레드가 끝없이 늘어 서버가 무너지지 않는다
#
# ■ 생산자-소비자 (Pintos의 유한 버퍼와 같은 문제)
#   queue.Queue가 안에서 락 + 조건 변수로 해 준다: 큐가 비면 작업자는 get()에서 잠들고, 일이 들어오면 하나가 깨어난다.
#   큐가 꽉 차면 submit은 기다리지 않고 False → 서버가 바로 503으로 거절한다 (백프레셔: 감당 못 할 일은 받지 않는다)
#
# ■ 멈추기: 큐에 "그만"(None)을 작업자 수만큼 넣는다. 작업자는 앞에 쌓인 일을 다 끝낸 뒤 None을 꺼내고 끝난다

import queue
import sys
import threading
import traceback


class ThreadPool:
    def __init__(self, workers, queue_size):
        for name, value in (("workers", workers), ("queue_size", queue_size)):
            # queue.Queue(maxsize=0)은 "무제한"이라 0을 받으면 백프레셔가 사라진다 → 1 이상만
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name}은(는) 1 이상의 정수여야 합니다")
        self._tasks = queue.Queue(maxsize=queue_size)
        self._threads = [threading.Thread(target=self._work, name=f"minidb-worker-{i + 1}", daemon=True)
                         for i in range(workers)]
        for thread in self._threads:
            thread.start()

    # 일 하나를 큐에 넣는다 → 넣었으면 True, 큐가 꽉 찼으면 False (기다리지 않는다)
    def submit(self, fn, *args):
        try:
            self._tasks.put_nowait((fn, args))
            return True
        except queue.Full:
            return False

    def _work(self):
        while True:
            task = self._tasks.get()  # 큐가 비어 있으면 여기서 잠든다
            if task is None:
                return
            fn, args = task
            try:
                fn(*args)
            except Exception:  # 일 하나가 실패해도 작업자는 죽지 않고 다음 일을 한다 (작업자가 줄어들지 않게)
                traceback.print_exc(file=sys.stderr)

    # 큐에 쌓인 일을 모두 끝낸 뒤 작업자를 멈춘다
    def stop(self):
        for _ in self._threads:
            self._tasks.put(None)  # 꽉 찼으면 작업자가 일을 꺼내 자리가 날 때까지 기다린다
        for thread in self._threads:
            thread.join()
