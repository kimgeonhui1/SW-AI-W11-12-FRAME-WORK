# [test_benchmark.py] 벤치마크 도구의 기능 테스트 — 요청 수, 캐시 상태 집계, 시간 계산, 오류 처리, 서버 정리
# "캐시가 더 빠르다"는 속도 비교는 여기서 검사하지 않는다 (속도는 실행 환경에 따라 달라지는 관측값이지 합격 기준이 아니다)

import json
import math
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

from demo import api_server, benchmark


def ok(cache):
    return (200, json.dumps({"item": {"id": 1}, "cache": cache}).encode())


class StubApi:
    """정해 둔 응답을 차례로 돌려주는 가짜 데모 API. 받은 요청(메서드, 경로)을 모두 기록한다"""

    def __init__(self, script=None, responder=None):
        self.script = list(script or [])
        self.responder = responder  # 경로를 보고 응답을 정하는 함수 (script보다 우선)
        self.log = []
        self.lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _any(self):
                with stub.lock:
                    stub.log.append((self.command, self.path))
                    step = stub.responder(self.path) if stub.responder else stub.script.pop(0)
                if step[0] == "sleep":  # 응답을 늦게 보내 시간 초과를 만든다
                    time.sleep(step[1])
                    step = ok("HIT")
                status, data = step
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:  # 시간 초과로 클라이언트가 먼저 끊은 경우
                    pass

            do_GET = do_PUT = do_POST = do_DELETE = _any

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def port_is_closed(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
    except OSError:
        return True
    return False


def closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeClock:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        return self.values.pop(0)


def fake_result(durations, statuses=None, requested=None, errors=None):
    full = {key: 0 for key in benchmark.STATUS_KEYS}
    full.update(statuses or {})
    return benchmark._summary("fake", requested if requested is not None else len(durations), durations, full, errors or {})


class MeasureTest(unittest.TestCase):
    def stub(self, **kwargs):
        stub = StubApi(**kwargs)
        self.addCleanup(stub.close)
        return stub

    def test_sends_exactly_n_get_requests(self):
        stub = self.stub(script=[ok("HIT")] * 7)
        result = benchmark.measure(stub.url + "/items/1", 7)
        self.assertEqual(stub.log, [("GET", "/items/1")] * 7)
        self.assertEqual((result["requested"], result["succeeded"], result["failed"]), (7, 7, 0))
        self.assertEqual(len(result["durations_ms"]), 7)

    def test_tallies_cache_statuses_including_unknown(self):
        stub = self.stub(script=[ok("HIT"), ok("HIT"), ok("MISS"), ok("OFF"), ok("BYPASS"), ok("WARM"), ok("hit")])
        result = benchmark.measure(stub.url + "/items/1", 7)
        self.assertEqual(result["statuses"], {"HIT": 2, "MISS": 1, "OFF": 1, "BYPASS": 1, "unknown": 2})
        self.assertEqual((result["succeeded"], result["failed"]), (7, 0))  # 모르는 문자열은 실패가 아니라 unknown

    def test_time_calculation_uses_injected_clock(self):
        stub = self.stub(script=[ok("HIT")] * 3)
        clock = FakeClock([0.0, 0.010, 1.0, 1.030, 2.0, 2.020])  # 요청마다 (시작, 끝) → 10ms, 30ms, 20ms
        result = benchmark.measure(stub.url + "/items/1", 3, clock=clock)
        for got, want in zip(result["durations_ms"], [10.0, 30.0, 20.0]):
            self.assertAlmostEqual(got, want, places=6)
        self.assertAlmostEqual(result["mean_ms"], 20.0, places=6)
        self.assertAlmostEqual(result["median_ms"], 20.0, places=6)
        self.assertEqual(clock.values, [])  # 시계를 요청당 정확히 2번 불렀다

    def test_default_clock_is_monotonic(self):
        self.assertIs(benchmark.measure.__defaults__[1], time.perf_counter)
        self.assertTrue(time.get_clock_info("perf_counter").monotonic)

    def test_failures_are_counted_and_excluded_from_mean(self):
        stub = self.stub(script=[
            ok("HIT"),
            (500, b'{"error": "x"}'),
            (200, b"not json"),
            (200, b'{"item": {}}'),  # cache 필드 누락 → 실패
            (200, b"[1, 2]"),  # JSON이지만 객체가 아님
            (200, b'{"cache": 5}'),  # cache가 문자열이 아님
            (404, b'{"error": "x", "cache": "MISS"}'),  # 200이 아니면 cache 필드가 있어도 실패
            ok("MISS"),
        ])
        clock = FakeClock([0, 0.010, 1, 2, 3, 4, 4.5, 5, 5.5, 6, 6.5, 7, 8, 8.050])
        result = benchmark.measure(stub.url + "/items/1", 8, clock=clock)
        self.assertEqual((result["requested"], result["succeeded"], result["failed"]), (8, 2, 6))
        self.assertEqual(result["errors"], {"http_500": 1, "bad_json": 1, "missing_cache": 1, "bad_shape": 1,
                                            "bad_cache_type": 1, "http_404": 1})
        self.assertEqual(result["statuses"], {"HIT": 1, "MISS": 1, "OFF": 0, "BYPASS": 0, "unknown": 0})
        self.assertAlmostEqual(result["mean_ms"], 30.0, places=6)  # 성공한 10ms, 50ms만으로 계산
        self.assertEqual(len(stub.log), 8)  # 실패해도 멈추지 않고 끝까지 보냈다

    def test_timeout_is_a_failure_and_run_continues(self):
        stub = self.stub(script=[("sleep", 0.6), ok("HIT")])
        result = benchmark.measure(stub.url + "/items/1", 2, timeout=0.15)
        self.assertEqual(result["errors"], {"timeout": 1})
        self.assertEqual((result["succeeded"], result["failed"]), (1, 1))

    def test_connection_refused_gives_zero_successes_and_none_mean(self):
        result = benchmark.measure(f"http://127.0.0.1:{closed_port()}/items/1", 3, timeout=1)
        self.assertEqual((result["succeeded"], result["failed"]), (0, 3))
        self.assertEqual(sum(result["errors"].values()), 3)
        self.assertIsNone(result["mean_ms"])
        self.assertIsNone(result["median_ms"])

    def test_unexpected_exception_is_not_swallowed(self):
        stub = self.stub(script=[ok("HIT")])

        def broken_clock():
            raise RuntimeError("clock broke")

        with self.assertRaises(RuntimeError):
            benchmark.measure(stub.url + "/items/1", 1, clock=broken_clock)

    def test_invalid_n_and_timeout(self):
        for n in (0, -1, True, 1.5, "3", None):
            with self.assertRaises(ValueError, msg=repr(n)):
                benchmark.measure("http://127.0.0.1:1/x", n)
        for timeout in (0, -1, math.inf, math.nan, True, "1", None, 10 ** 400):
            with self.assertRaises(ValueError, msg=repr(timeout)):
                benchmark.measure("http://127.0.0.1:1/x", 1, timeout=timeout)


class RunTest(unittest.TestCase):
    """run_benchmark: 묶음 순서, 전체 집계, 상태 표시, 외부 URL 모드"""

    def run_quiet(self, **kwargs):
        lines = []
        report = benchmark.run_benchmark(out=lines.append, **kwargs)
        return report, "\n".join(lines)

    def external(self, on="HIT", off="OFF"):
        def responder(path):
            if path.endswith("?cache=off"):
                return off if isinstance(off, tuple) else ok(off)
            return on if isinstance(on, tuple) else ok(on)

        stub = StubApi(responder=responder)
        self.addCleanup(stub.close)
        return stub

    def test_round_order_alternates(self):
        self.assertEqual(benchmark.round_order(1), [("on", "off")])
        self.assertEqual(benchmark.round_order(4), [("on", "off"), ("off", "on"), ("on", "off"), ("off", "on")])
        for rounds in (0, -2, True, 2.0, "2"):
            with self.assertRaises(ValueError, msg=repr(rounds)):
                benchmark.round_order(rounds)

    def test_external_mode_sends_only_gets_in_alternating_order_and_leaves_server_running(self):
        stub = self.external()
        report, text = self.run_quiet(n=2, rounds=3, api_url=stub.url + "/")
        on, off = "/items/1", "/items/1?cache=off"
        self.assertEqual([path for _, path in stub.log], [on] + [on, on, off, off] + [off, off, on, on] + [on, on, off, off])
        self.assertEqual({method for method, _ in stub.log}, {"GET"})
        self.assertEqual((report["status"], report["exit_code"]), ("COMPLETE", 0))
        self.assertEqual(report["cleanup_problems"], [])
        self.assertEqual(report["modes"]["on"]["requested"], 6)
        self.assertEqual(report["modes"]["on"]["statuses"]["HIT"], 6)
        self.assertEqual(report["modes"]["off"]["statuses"]["OFF"], 6)
        self.assertEqual(report["warmup"]["requested"], 1)
        with urlopen(stub.url + "/items/1", timeout=2) as res:  # 외부 서버는 끝난 뒤에도 그대로 응답한다
            self.assertEqual(res.status, 200)
        self.assertTrue(stub.thread.is_alive())
        self.assertIn("인위적 지연", text)
        self.assertIn("Poker 서비스의 성능 측정이 아닙니다", text)
        self.assertIn("unknown=0", text)
        self.assertIn("전체 요청 성공을 뜻하지 않습니다", text)

    def test_overall_mean_and_median_use_every_individual_duration(self):
        # cache-on: 1묶음 [10], 2묶음 [20, 30, 40] → 전체 평균 25, 중앙값 25 (묶음 평균의 평균이면 20, 묶음 중앙값의 중앙값이면 20)
        calls = iter([
            fake_result([1.0], {"MISS": 1}),  # 워밍업
            fake_result([10.0], {"HIT": 1}, requested=3, errors={"timeout": 2}),  # 1묶음 on
            fake_result([100.0, 100.0, 100.0], {"OFF": 3}),  # 1묶음 off
            fake_result([200.0, 200.0, 200.0], {"OFF": 3}),  # 2묶음 off
            fake_result([20.0, 30.0, 40.0], {"HIT": 3}),  # 2묶음 on
        ])
        report, text = self.run_quiet(n=3, rounds=2, api_url="http://example.invalid",
                                      measure_fn=lambda url, n, timeout, clock: next(calls))
        on = report["modes"]["on"]
        self.assertEqual(on["mean_ms"], 25.0)
        self.assertEqual(on["median_ms"], 25.0)
        self.assertEqual((on["requested"], on["succeeded"], on["failed"]), (6, 4, 2))
        self.assertEqual(report["modes"]["off"]["mean_ms"], 150.0)
        self.assertEqual((report["status"], report["exit_code"]), ("PARTIAL", 0))  # 일부 실패 → PARTIAL로 표시
        self.assertIn("STATUS: PARTIAL", text)
        self.assertIn("timeout 2건", text)

    def test_partial_failures_from_real_http_are_reported(self):
        answers = iter([ok("HIT"), ok("HIT"), (500, b"{}"), ok("HIT"), ok("HIT")])
        stub = self.external(on="HIT")
        stub.responder = lambda path: ok("OFF") if path.endswith("off") else next(answers)
        report, text = self.run_quiet(n=2, rounds=2, api_url=stub.url)
        self.assertEqual(report["modes"]["on"]["failed"], 1)
        self.assertEqual((report["status"], report["exit_code"]), ("PARTIAL", 0))
        self.assertIn("요청 1건 실패", text)

    def test_mode_with_zero_successes_is_failed_with_nonzero_exit(self):
        stub = self.external(on=(500, b"{}"))
        report, text = self.run_quiet(n=2, rounds=1, api_url=stub.url)
        self.assertEqual((report["status"], report["exit_code"]), ("FAILED", benchmark.EXIT_FAILED))
        self.assertIsNone(report["modes"]["on"]["mean_ms"])
        self.assertIn("STATUS: FAILED", text)

    def test_condition_mismatch_is_degraded(self):
        stub = self.external(on="OFF", off="HIT")  # 서로 뒤바뀐 상태
        report, text = self.run_quiet(n=2, rounds=1, api_url=stub.url)
        self.assertEqual((report["status"], report["exit_code"]), ("DEGRADED", 0))
        self.assertIn("비교 조건 불일치: cache-on에 OFF 2건", text)
        self.assertIn("비교 조건 불일치: cache-off에 OFF가 아닌 상태 (HIT 2건)", text)

    def test_unknown_status_is_printed_and_degraded(self):
        stub = self.external(on="WARM")
        report, text = self.run_quiet(n=2, rounds=1, api_url=stub.url)
        self.assertEqual(report["modes"]["on"]["statuses"]["unknown"], 2)
        self.assertEqual(report["status"], "DEGRADED")
        self.assertIn("unknown=2", text)
        self.assertIn("unknown 2건", text)

    def test_invalid_arguments(self):
        for kwargs in ({"n": 0}, {"rounds": 0}, {"rounds": True}, {"timeout": math.inf}, {"timeout": 0},
                       {"api_url": "localhost:8000"}, {"item_id": 0}):
            with self.assertRaises(ValueError, msg=repr(kwargs)):
                benchmark.run_benchmark(out=lambda line: None, **{"api_url": "http://example.invalid", **kwargs})
        for argv in (["--n", "0"], ["--rounds", "x"], ["--timeout", "inf"], ["--timeout", "-1"], ["--api", "localhost"]):
            with self.assertRaises(SystemExit, msg=repr(argv)):
                with self.assertLogsNothing():
                    benchmark.main(argv, out=lambda line: None)

    def assertLogsNothing(self):
        # argparse가 사용법을 stderr에 찍는 것을 테스트 출력에서 숨긴다
        import contextlib, io
        return contextlib.redirect_stderr(io.StringIO())


class SelfHostedTest(unittest.TestCase):
    """자체 기동 모드: 실제 Mini Redis + 데모 API를 띄우고, 어떤 경우에도 닫히는지 확인"""

    def setUp(self):
        self.saved_delay = api_server.SLOW_DELAY
        self.saved_client = api_server.redis
        api_server.SLOW_DELAY = 0.01  # 원본 조회 지연을 줄여 테스트를 빠르게
        self.servers = []
        self.threads_before = set(threading.enumerate())

        def restore():
            api_server.SLOW_DELAY = self.saved_delay
            api_server.redis = self.saved_client

        self.addCleanup(restore)

    def make_redis(self):
        server = benchmark._make_redis_server()
        self.servers.append(server)
        return server

    def make_api(self, redis_url):
        server = benchmark._make_api_server(redis_url)
        self.servers.append(server)
        return server

    def run_quiet(self, **kwargs):
        lines = []
        kwargs.setdefault("make_redis", self.make_redis)
        kwargs.setdefault("make_api", self.make_api)
        report = benchmark.run_benchmark(out=lines.append, **kwargs)
        return report, "\n".join(lines)

    def assert_cleaned_up(self, report, expected_servers):
        self.assertEqual(report["cleanup_problems"], [])
        self.assertEqual(len(self.servers), expected_servers)
        for server in self.servers:
            self.assertTrue(port_is_closed(server.server_address[1]))
        left = [t.name for t in threading.enumerate() if t not in self.threads_before and t.is_alive()]
        self.assertEqual(left, [])
        self.assertIs(api_server.redis, self.saved_client)  # 바꿔 끼웠던 전역 클라이언트도 되돌렸다

    def test_normal_run_reports_and_cleans_up(self):
        report, text = self.run_quiet(n=3, rounds=2)
        self.assertEqual((report["status"], report["exit_code"]), ("COMPLETE", 0))
        self.assertEqual(report["warmup"]["statuses"]["MISS"], 1)  # 첫 요청은 MISS → 워밍업으로 분리
        self.assertEqual(report["modes"]["on"]["statuses"], {"HIT": 6, "MISS": 0, "OFF": 0, "BYPASS": 0, "unknown": 0})
        self.assertEqual(report["modes"]["off"]["statuses"], {"HIT": 0, "MISS": 0, "OFF": 6, "BYPASS": 0, "unknown": 0})
        self.assertEqual([row["order"] for row in report["rounds"]], [("on", "off"), ("off", "on")])
        self.assertIn("자체 기동한 서버 정리 완료", text)
        self.assertIn("SLOW_DELAY = 0.01초", text)
        self.assert_cleaned_up(report, 2)

    def test_exception_during_measurement_still_cleans_up(self):
        calls = []

        def exploding(url, n, timeout, clock):
            calls.append(url)
            if len(calls) == 3:
                raise RuntimeError("측정 중 고장")
            return benchmark.measure(url, n, timeout=timeout, clock=clock)

        report, text = self.run_quiet(n=2, rounds=2, measure_fn=exploding)
        self.assertEqual((report["status"], report["exit_code"]), ("ERROR", benchmark.EXIT_ERROR))
        self.assertIn("RuntimeError", report["error"])
        self.assertIn("STATUS: ERROR", text)
        self.assert_cleaned_up(report, 2)

    def test_second_server_start_failure_closes_first_server(self):
        def failing_api(redis_url):
            raise OSError("포트를 열 수 없음")

        report, text = self.run_quiet(make_api=failing_api)
        self.assertEqual((report["status"], report["exit_code"]), ("ERROR", benchmark.EXIT_ERROR))
        self.assertIn("OSError", report["error"])
        self.assertEqual(report["modes"], {})
        self.assert_cleaned_up(report, 1)  # 먼저 띄운 Mini Redis가 닫혔다

    def test_first_server_start_failure_is_error(self):
        def failing_redis():
            raise OSError("포트를 열 수 없음")

        report, _ = self.run_quiet(make_redis=failing_redis)
        self.assertEqual(report["exit_code"], benchmark.EXIT_ERROR)
        self.assert_cleaned_up(report, 0)

    def test_redis_unavailable_is_bypass_and_degraded(self):
        dead = f"http://127.0.0.1:{closed_port()}"
        report, text = self.run_quiet(n=2, rounds=1, make_api=lambda redis_url: self.make_api(dead))
        self.assertEqual(report["modes"]["on"]["statuses"]["BYPASS"], 2)
        self.assertEqual(report["modes"]["on"]["failed"], 0)  # 캐시가 죽어도 요청 자체는 성공한다
        self.assertEqual((report["status"], report["exit_code"]), ("DEGRADED", 0))
        self.assertIn("BYPASS 2건", text)
        self.assert_cleaned_up(report, 2)

    def test_main_returns_exit_code(self):
        lines = []
        self.assertEqual(benchmark.main(["--n", "1", "--rounds", "1"], out=lines.append), 0)
        self.assertTrue(any(line.startswith("STATUS: COMPLETE") for line in lines))
        left = [t.name for t in threading.enumerate() if t not in self.threads_before and t.is_alive()]
        self.assertEqual(left, [])


class StopServersTest(unittest.TestCase):
    """stop_servers: 종료 대기에 상한이 있고, 끝나지 않은 것은 정리 실패로 보고한다"""

    def test_hung_shutdown_is_reported_within_the_wait_limit(self):
        release = threading.Event()
        self.addCleanup(release.set)

        class HungServer:
            closed = False

            def shutdown(self):
                release.wait(30)

            def server_close(self):
                self.closed = True

        entry = benchmark._Started("hung", HungServer())
        entry.thread = threading.Thread(target=release.wait, args=(30,), daemon=True, name="bench-hung")
        baseline = set(threading.enumerate())
        entry.thread.start()
        began = time.monotonic()
        problems = benchmark.stop_servers([entry], baseline, wait=0.3)
        self.assertLess(time.monotonic() - began, 3)  # 30초를 기다리지 않고 상한에서 돌아온다
        self.assertTrue(entry.server.closed)
        text = " / ".join(problems)
        self.assertIn("shutdown이", text)
        self.assertIn("서버 스레드가 끝나지 않았습니다", text)
        release.set()
        entry.thread.join(5)

    def test_cleanup_failure_changes_exit_code(self):
        release = threading.Event()
        self.addCleanup(release.set)

        class Leaky:
            server_address = ("127.0.0.1", 9)

            def serve_forever(self):
                release.wait(30)

            def shutdown(self):
                pass

            def server_close(self):
                pass

        lines = []
        report = benchmark.run_benchmark(
            n=1, rounds=1, out=lines.append, stop_wait=0.3,
            make_redis=Leaky, make_api=lambda redis_url: Leaky(),
            measure_fn=lambda url, n, timeout, clock: fake_result([1.0], {"OFF" if url.endswith("off") else "HIT": 1}))
        self.assertTrue(report["cleanup_problems"])
        self.assertEqual(report["exit_code"], benchmark.EXIT_CLEANUP)
        self.assertTrue(any(line.startswith("정리 실패:") for line in lines))

    def test_server_never_started_is_closed_without_calling_shutdown(self):
        class NeverServed:
            closed = False

            def shutdown(self):
                raise AssertionError("serve_forever를 시작하지 않은 서버에 shutdown을 부르면 영원히 멈춘다")

            def server_close(self):
                self.closed = True

        entry = benchmark._Started("idle", NeverServed())
        self.assertEqual(benchmark.stop_servers([entry], set(threading.enumerate()), wait=0.5), [])
        self.assertTrue(entry.server.closed)


if __name__ == "__main__":
    unittest.main()
