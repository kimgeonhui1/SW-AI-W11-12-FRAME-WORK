# [test_concurrency.py] 읽기-쓰기 락과 스레드 풀 (Phase 3)

import contextlib
import io
import threading
import time
import unittest

from minidb.rwlock import RWLock
from minidb.threadpool import ThreadPool

WAIT = 2  # 테스트가 영원히 멈추지 않게 하는 기다림 상한(초)


class RWLockTest(unittest.TestCase):
    def test_readers_share_the_lock(self):
        lock, inside, both = RWLock(), [], threading.Barrier(2, timeout=WAIT)

        def reader():
            with lock.read():
                inside.append(1)
                both.wait()  # 두 읽기가 동시에 안에 있어야 통과한다 (아니면 BrokenBarrierError)

        threads = [threading.Thread(target=reader) for _ in range(2)]
        [t.start() for t in threads]
        [t.join(WAIT) for t in threads]
        self.assertEqual(len(inside), 2)
        self.assertFalse(both.broken)

    def test_writer_is_alone(self):
        lock, events = RWLock(), []
        reading = threading.Event()

        def reader():
            with lock.read():
                reading.set()
                time.sleep(0.2)
                events.append("read-end")

        def writer():
            reading.wait(WAIT)
            with lock.write():
                events.append("write")

        threads = [threading.Thread(target=reader), threading.Thread(target=writer)]
        [t.start() for t in threads]
        [t.join(WAIT) for t in threads]
        self.assertEqual(events, ["read-end", "write"])  # 읽는 동안 쓰기는 기다렸다

    def test_waiting_writer_blocks_new_readers(self):
        # 쓰기 굶주림 방지: 쓰기가 기다리는 중이면 새로 온 읽기는 쓰기 뒤에 들어간다
        lock, events = RWLock(), []
        first_reading, writer_waiting = threading.Event(), threading.Event()

        def first_reader():
            with lock.read():
                first_reading.set()
                writer_waiting.wait(WAIT)
                time.sleep(0.1)  # 쓰기가 기다리는 상태에서 새 읽기가 도착할 시간
                events.append("first-read-end")

        def writer():
            first_reading.wait(WAIT)
            writer_waiting.set()
            with lock.write():
                events.append("write")

        def late_reader():
            writer_waiting.wait(WAIT)
            time.sleep(0.05)
            with lock.read():
                events.append("late-read")

        threads = [threading.Thread(target=f) for f in (first_reader, writer, late_reader)]
        [t.start() for t in threads]
        [t.join(WAIT) for t in threads]
        self.assertEqual(events, ["first-read-end", "write", "late-read"])

    def test_exception_inside_releases(self):
        lock = RWLock()
        for mode in (lock.read, lock.write):
            with self.assertRaises(ZeroDivisionError):
                with mode():
                    1 / 0
        done = threading.Event()
        threading.Thread(target=lambda: (lock.write().__enter__(), done.set())).start()
        self.assertTrue(done.wait(WAIT))  # 예외 뒤에도 쓰기 락을 잡을 수 있다 = 둘 다 풀렸다


class ThreadPoolTest(unittest.TestCase):
    def test_runs_tasks_in_parallel_on_fixed_workers(self):
        pool = ThreadPool(workers=4, queue_size=10)
        started, names = threading.Barrier(4, timeout=WAIT), set()

        def task():
            names.add(threading.current_thread().name)
            started.wait()  # 4개가 동시에 실행 중이어야 통과

        for _ in range(4):
            self.assertTrue(pool.submit(task))
        for _ in range(4):
            self.assertTrue(pool.submit(lambda: names.add(threading.current_thread().name)))
        pool.stop()
        self.assertFalse(started.broken)
        self.assertEqual(len(names), 4)  # 일 8개를 작업자 4개가 나눠 했다 (스레드를 새로 만들지 않음)

    def test_full_queue_rejects_without_waiting(self):
        pool = ThreadPool(workers=1, queue_size=1)
        release = threading.Event()
        self.assertTrue(pool.submit(release.wait, WAIT))  # 작업자가 이 일을 잡고 멈춰 있다
        time.sleep(0.1)
        self.assertTrue(pool.submit(lambda: None))  # 큐 1칸
        start = time.perf_counter()
        self.assertFalse(pool.submit(lambda: None))  # 꽉 참 → 바로 False
        self.assertLess(time.perf_counter() - start, 0.5)
        release.set()
        pool.stop()

    def test_failing_task_does_not_kill_worker(self):
        pool = ThreadPool(workers=1, queue_size=5)
        done = threading.Event()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            pool.submit(lambda: 1 / 0)
            pool.submit(done.set)
            self.assertTrue(done.wait(WAIT))  # 같은 작업자가 다음 일을 했다
            pool.stop()
        self.assertIn("ZeroDivisionError", err.getvalue())

    def test_stop_finishes_queued_tasks(self):
        pool = ThreadPool(workers=2, queue_size=20)
        done = []
        for i in range(20):
            pool.submit(done.append, i)
        pool.stop()
        self.assertEqual(sorted(done), list(range(20)))

    def test_bad_sizes(self):
        for workers, size in [(0, 1), (1, 0), (-1, 5), (True, 5), (2.5, 5), (2, "8")]:
            with self.assertRaises(ValueError, msg=(workers, size)):
                ThreadPool(workers, size)


if __name__ == "__main__":
    unittest.main()
