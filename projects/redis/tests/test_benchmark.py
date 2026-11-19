# [test_benchmark.py] 성능 비교 스크립트가 올바르게 측정하는지 확인 (숫자 자체가 아니라 측정 방식)
# 성능 숫자는 컴퓨터마다 다르므로, "무엇을 쟀는가(HIT/OFF/MISS, 요청 수, 적중률)"와 "물리적으로 반드시 성립하는 하한·상한"만 검사한다

import contextlib
import io
import json
import math
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock
from urllib.error import HTTPError, URLError

from demo import api_server, benchmark

SVG = "{http://www.w3.org/2000/svg}"


@contextlib.contextmanager
def fake_server(status, body):
    """항상 같은 응답을 주는 서버 (측정 대상이 에러나 이상한 응답을 줄 때를 흉내)"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/items/1"
    finally:
        server.shutdown()
        server.server_close()


class BenchmarkTest(unittest.TestCase):
    def setUp(self):
        # 측정 함수가 서버를 띄우면 api_server.redis(전역 클라이언트)가 바뀐다 → 다른 테스트에 남지 않게 되돌린다
        self.addCleanup(setattr, api_server, "redis", api_server.redis)

    # ───────── ① 기본 비교 ─────────

    def test_cache_is_faster_and_all_hits(self):
        without_cache, with_cache = benchmark.run(n=5, delay=0.05)
        # 측정 구간이 의도대로인지: 미사용은 전부 OFF, 사용은 전부 HIT여야 공정한 비교다
        self.assertEqual((without_cache["cache"], with_cache["cache"]), ("OFF", "HIT"))
        self.assertEqual((without_cache["count"], with_cache["count"]), (5, 5))  # 캐시 채우기(MISS)는 측정에 안 들어감
        self.assertGreaterEqual(without_cache["min"], 50)  # 원본 지연 50ms가 매번 들어감 (물리적 하한이라 결정적)
        # "캐시가 더 빠른가"는 시간 비교라 PerformanceComparisonTest로 옮겼다 (CI 부하에 흔들리지 않게 기능 검증과 분리)
        for r in (without_cache, with_cache):
            self.assertTrue(r["min"] <= r["p50"] <= r["p95"] <= r["max"])

    def test_invalid_n(self):
        with self.assertRaises(ValueError):
            benchmark.measure("http://127.0.0.1:1", 0)

    def test_invalid_args_rejected_before_servers_start(self):
        for n, delay in [(0, 0.1), (True, 0.1), (1.5, 0.1), (1, -1), (1, float("nan")), (1, float("inf")), (1, True)]:
            with self.assertRaises(ValueError, msg=(n, delay)):
                benchmark.run(n, delay)
        for item_id in [0, -1, api_server.ITEM_COUNT + 1, "1", True, 1.0]:  # 없는 아이템이면 404만 재게 된다 (Gemini 리뷰)
            with self.assertRaises(ValueError, msg=item_id):
                benchmark.run(1, 0.01, item_id)

    def test_run_restores_slow_delay(self):
        # run이 바꾼 원본 지연 시간이 같은 프로세스의 다른 코드(데모 테스트 등)에 남지 않아야 한다
        before = api_server.SLOW_DELAY
        benchmark.run(n=1, delay=0.01)
        self.assertEqual(api_server.SLOW_DELAY, before)

    # ───────── ② 원본 지연별 ─────────

    def test_delay_sweep_measures_each_delay(self):
        before = api_server.SLOW_DELAY
        results = benchmark.delay_sweep(3, [0, 0.03])
        self.assertEqual([d for d, _, _ in results], [0, 0.03])
        for delay, without_cache, with_cache in results:
            self.assertEqual((without_cache["cache"], with_cache["cache"]), ("OFF", "HIT"), delay)
            self.assertEqual((without_cache["count"], with_cache["count"]), (3, 3))
        # 지연이 바뀐 게 실제로 반영됐는지: 30ms 원본은 매번 30ms 이상 (물리적 하한: 측정값 = sleep + HTTP 왕복)
        # 0ms 원본보다 느린지는 시간 비교라 PerformanceComparisonTest에서 검사한다
        self.assertGreaterEqual(results[1][1]["min"], 30)
        self.assertEqual(api_server.SLOW_DELAY, before)  # 지연을 여러 번 바꿔도 끝나면 원래대로

    def test_delay_sweep_accepts_any_iterable(self):
        # 튜플·제너레이터도 받는다 (한 번만 돌 수 있는 제너레이터를 검사하느라 다 써 버리면 측정할 게 없어진다)
        results = benchmark.delay_sweep(1, (d for d in [0]))
        self.assertEqual(len(results), 1)

    # ───────── ③ 적중률별 ─────────

    def test_hit_ratio_matches_plan(self):
        results = benchmark.hit_ratio(20, 0.02, [0, 0.25, 1])
        self.assertEqual([r["hit"] for _, r in results], [0, 0.25, 1])
        # MISS 요청은 같은 아이템을 반복해도 매번 진짜 MISS여야 한다 (지우지 않으면 두 번째부터 HIT가 되어 적중률이 틀어진다)
        self.assertEqual([r["cache"] for _, r in results], ["MISS", "HIT/MISS", "HIT"])
        self.assertEqual([r["count"] for _, r in results], [20, 20, 20])
        self.assertGreaterEqual(results[0][1]["min"], 20)  # 적중률 0%: 모든 요청이 원본(20ms)을 거친다
        # MISS가 HIT보다 느린지는 PerformanceComparisonTest에서 검사한다

    def test_hit_ratio_rounds_to_whole_requests(self):
        # 요청 3번의 50% → 1.5번은 불가능하므로 반올림한 2번이 HIT (실제 적중률 2/3을 그대로 보고한다)
        (_, r), = benchmark.hit_ratio(3, 0.01, [0.5])
        self.assertAlmostEqual(r["hit"], 2 / 3)

    def test_hit_ratio_does_not_touch_other_items(self):
        # MISS를 만들려고 지우는 것은 아이템 2번의 캐시뿐이어야 한다 (HIT용 1번이 지워지면 HIT가 MISS로 바뀐다)
        results = benchmark.hit_ratio(10, 0.01, [0.5, 1])
        self.assertEqual(results[1][1]["cache"], "HIT")

    # ───────── ④ 동시 요청 ─────────

    def test_load_counts_and_states(self):
        results = benchmark.load(0.02, [1, 4], 3)
        self.assertEqual([c for c, _, _ in results], [1, 4])
        for clients, without_cache, with_cache in results:
            self.assertEqual((without_cache["count"], with_cache["count"]), (clients * 3, clients * 3))  # 요청을 빠뜨리지 않음
            self.assertEqual((without_cache["cache"], with_cache["cache"]), ("OFF", "HIT"))
            self.assertGreater(without_cache["rps"], 0)

    def test_source_pool_caps_throughput_without_cache(self):
        # 원본 동시 연결이 5개이므로, 캐시 없이는 아무리 많이 동시에 보내도 초당 5 / 지연 건을 넘을 수 없다 (물리적 상한)
        # 지연 0.1초 · 10명: 상한(초당 50건)과 캐시 처리량의 차이가 커서 느린 CI에서도 순서가 뒤집히지 않는다 (Gemini 리뷰)
        delay = 0.1
        (_, without_cache, with_cache), = benchmark.load(delay, [10], 2)
        cap = api_server.SOURCE_CONNECTIONS / delay
        # 시작 시각을 출발 순간에 재므로 여유 없이 상한 이하여야 한다 (요청 20개 ÷ 동시 5개 = 4번 × 0.1초 이상 걸린다)
        self.assertLessEqual(without_cache["rps"], cap)
        self.assertEqual(with_cache["cache"], "HIT")  # 캐시 처리량이 더 큰지는 PerformanceComparisonTest에서 검사한다

    def test_concurrent_error_in_worker_is_raised(self):
        # 스레드 안에서 난 에러가 조용히 사라지면 "요청 수가 적은 결과"가 정상처럼 출력된다 → 반드시 밖으로 알린다
        with fake_server(500, b'{"error": "x"}') as url:
            with self.assertRaises(HTTPError) as cm:
                benchmark._concurrent(url, 3, 2)
            self.assertTrue(cm.exception.fp is None or cm.exception.fp.closed)  # 던지기 전에 연결을 닫았다

    # ───────── 측정 대상이 이상할 때 ─────────

    def test_bad_responses_fail_loudly(self):
        # 측정 대상이 에러·약속과 다른 응답을 주면 숫자를 내지 않고 실패해야 한다 (에러 응답 시간을 성능으로 착각하지 않게)
        for status, body, error in [(500, b'{"error": "x"}', HTTPError), (200, b'{"item": {}}', KeyError),
                                    (200, b"not json", json.JSONDecodeError)]:
            with self.subTest(status=status, body=body), fake_server(status, body) as url:
                with self.assertRaises(error) as cm:
                    benchmark.measure(url, 2)

    def test_servers_closed_and_delay_restored_after_error(self):
        before = api_server.SLOW_DELAY
        with self.assertRaises(RuntimeError):
            with benchmark._servers(0.123) as (base, _):
                port = int(base.rsplit(":", 1)[1])
                self.assertEqual(api_server.SLOW_DELAY, 0.123)
                raise RuntimeError("측정 중 에러")
        self.assertEqual(api_server.SLOW_DELAY, before)
        with self.assertRaises(OSError):  # 포트가 닫혀 연결 불가 (거부 또는 시간 초과)
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()

    def test_invalid_conditions_rejected_before_servers_start(self):
        # 서버를 띄우면 api_server.redis가 새 클라이언트로 바뀐다 → 그대로면 서버를 안 띄우고 거부한 것
        client = api_server.redis
        nan, inf = float("nan"), float("inf")
        cases = [
            lambda: benchmark.delay_sweep(3, []),
            lambda: benchmark.delay_sweep(3, [0, -1]),
            lambda: benchmark.delay_sweep(3, [nan]),
            lambda: benchmark.delay_sweep(3, "0.1"),  # 문자열은 글자별로 돌면 안 된다
            lambda: benchmark.delay_sweep(3, None),
            lambda: benchmark.delay_sweep(0, [0]),
            lambda: benchmark.hit_ratio(3, 0.1, []),
            lambda: benchmark.hit_ratio(3, 0.1, [1.5]),
            lambda: benchmark.hit_ratio(3, 0.1, [-0.1]),
            lambda: benchmark.hit_ratio(3, 0.1, [nan]),
            lambda: benchmark.hit_ratio(3, 0.1, [True]),
            lambda: benchmark.hit_ratio(3, 0.1, ["0.5"]),
            lambda: benchmark.hit_ratio(3, inf, [0.5]),
            lambda: benchmark.load(0.1, []),
            lambda: benchmark.load(0.1, [0]),
            lambda: benchmark.load(0.1, [True]),
            lambda: benchmark.load(0.1, [2.5]),
            lambda: benchmark.load(0.1, [1], 0),
            lambda: benchmark.load(-1, [1], 1),
            lambda: benchmark.load(0.1, [10, 129]),  # 연결 대기열(128)을 넘는 동시 클라이언트 (연결 단계에 제한 시간이 없어서)
        ]
        for i, case in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(ValueError):
                case()
        self.assertIs(api_server.redis, client)

    def test_warn_if_not_hit(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertTrue(benchmark._warn_if_not_hit("x", [{"cache": "HIT"}]))
            self.assertFalse(benchmark._warn_if_not_hit("x", [{"cache": "HIT"}, {"cache": "BYPASS/HIT"}]))
        self.assertEqual(out.getvalue().count("[경고]"), 1)
        self.assertIn("BYPASS/HIT", out.getvalue())

    # ───────── 그래프 ─────────

    def test_axis_ticks(self):
        cases = {0: (1, 1), -5: (1, 1), 264: (100, 3), 300: (100, 3), 301: (100, 4), 1: (0.5, 2), 7.5: (2, 4), 0.33: (0.1, 4)}
        for peak, (step, ticks) in cases.items():
            got_step, got_ticks = benchmark._axis(peak)
            self.assertAlmostEqual(got_step, step, msg=peak)
            self.assertEqual(got_ticks, ticks, peak)
        for peak in [1e-9, 0.07, 3, 99, 100, 101, 249, 250, 251, 999, 12345, 1e9]:
            step, ticks = benchmark._axis(peak)
            self.assertGreaterEqual(step * ticks * (1 + 1e-12), peak)  # 맨 위 눈금이 값보다 작으면 막대가 잘린다
            self.assertTrue(2 <= ticks <= 4, (peak, ticks))  # 눈금이 너무 적거나 많지 않다
            mantissa = step / 10 ** math.floor(math.log10(step))
            self.assertTrue(any(math.isclose(mantissa, m) for m in (1, 2, 5)), (peak, step))  # 1·2·5 단위

    def test_fmt(self):
        self.assertEqual([benchmark._fmt(v) for v in [0, 100, 2500, 3.25, 12.6]], ["0", "100", "2,500", "3.2", "13"])

    def test_bar_chart_structure(self):
        svg = benchmark.bar_chart("제목 <&>", "부제", "ms", ["a", "b", "c"],
                                  [("미사용", "off", [100, 0, 3.5]), ("사용", "on", [5, 0, 1])], ref=("기준", 50))
        root = ET.fromstring(svg)  # 올바른 XML (특수문자가 이스케이프됨)
        self.assertEqual(root.find(f"{SVG}title").text, "제목 <&>")
        bars = root.findall(f"{SVG}path")
        self.assertEqual(len(bars), 6)  # 묶음 3 × 계열 2
        self.assertEqual([b.get("class") for b in bars], ["s-off", "s-on"] * 3)
        self.assertEqual(len(root.findall(f"{SVG}rect[@class='s-off']")), 1)  # 범례 (계열 2개라 있음)
        self.assertEqual(len(root.findall(f".//{SVG}line[@stroke-dasharray]")), 1)  # 기준선
        self.assertIn("prefers-color-scheme:dark", svg)  # 다크 모드 색

    def test_bar_heights_follow_values(self):
        root = ET.fromstring(benchmark.bar_chart("t", "s", "ms", ["a", "b"], [("x", "on", [10, 40])]))
        heights = []
        for bar in root.findall(f"{SVG}path"):
            d = bar.get("d").replace("M", "").replace("V", " ").split()
            heights.append(float(d[0].split(",")[1]) - float(d[1]))  # 기준선 y - 위쪽 y(둥근 모서리 시작점)
        self.assertGreater(heights[1], heights[0] * 3)  # 40은 10보다 4배 높아야 한다 (모서리 반지름만큼 오차)
        self.assertEqual(len(ET.fromstring(benchmark.bar_chart("t", "s", "ms", ["a"], [("x", "on", [1])]))
                             .findall(f"{SVG}rect[@class='s-on']")), 0)  # 계열 1개면 범례 없음

    def test_bar_chart_zero_and_tiny_values(self):
        for values in ([0, 0], [0, 1e-6], [0.0001, 5000]):
            root = ET.fromstring(benchmark.bar_chart("t", "s", "ms", ["a", "b"], [("x", "on", values)]))
            self.assertEqual(len(root.findall(f"{SVG}path")), 2, values)  # 0이어도 막대(1px)와 값 글자가 있다

    def test_bar_chart_rejects_bad_input(self):
        good = [("x", "on", [1, 2])]
        cases = [
            ([], good, None), (["a", "b"], [], None),
            (["a", "b"], [("x", "on", [1])], None),  # 값 개수 ≠ 묶음 개수
            (["a", "b"], [("x", "blue", [1, 2])], None),
            (["a", "b"], [("x", "on", [1, float("nan")])], None),
            (["a", "b"], [("x", "on", [1, float("inf")])], None),
            (["a", "b"], [("x", "on", [1, -2])], None),
            (["a", "b"], [("x", "on", [1, True])], None),
            (["a", "b"], [("x", "on", [1, "2"])], None),
            (["a", "b"], good, ("기준", float("nan"))),
        ]
        for groups, series, ref in cases:
            with self.subTest(groups=groups, series=series, ref=ref), self.assertRaises(ValueError):
                benchmark.bar_chart("t", "s", "ms", groups, series, ref=ref)

    def fake_results(self):
        stat = {"avg": 10.0, "p50": 9.0, "p95": 12.0, "min": 8.0, "max": 13.0, "cache": "HIT", "count": 3, "rps": 50.0, "hit": 0.8}
        return ([(0, dict(stat, avg=12.0), stat), (0.2, dict(stat, avg=200.0), stat)],
                [(0.8, stat), (1, dict(stat, hit=1.0))],
                [(1, dict(stat, rps=5.0), stat), (10, dict(stat, rps=25.0), dict(stat, rps=400.0))])

    def test_write_charts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "없는", "폴더")  # 없는 폴더도 만든다
            paths = benchmark.write_charts(out_dir, 3, 0.2, *self.fake_results(), baseline_ms=200.0)
            self.assertEqual(sorted(os.path.basename(p) for p in paths), ["concurrency.svg", "delay.svg", "hit-ratio.svg"])
            for path in paths:
                root = ET.parse(path).getroot()  # UTF-8로 저장된 올바른 SVG
                self.assertTrue(root.find(f"{SVG}title").text)
            hit_svg = ET.parse(os.path.join(out_dir, "hit-ratio.svg")).getroot()
            labels = [t.text for t in hit_svg.iter(f"{SVG}text")]
            self.assertIn("80%", labels)  # x축은 목표가 아니라 실제로 잰 적중률
            self.assertIn("100%", labels)

    def test_write_charts_to_file_path_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = os.path.join(tmp, "file")
            open(blocker, "w").close()
            with self.assertRaises(OSError):  # 폴더 자리에 파일이 있으면 OSError (main이 "측정 실패"로 알린다)
                benchmark.write_charts(blocker, 3, 0.2, *self.fake_results(), baseline_ms=200.0)

    # ───────── 명령줄 (main) ─────────

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.argv", ["benchmark", *argv]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                benchmark.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_main_end_to_end_small(self):
        # 측정 조건을 작게 바꿔 끝까지 실행 → 네 구간 표 + 그래프 3개, 경고 없음
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(benchmark, "SWEEP_DELAYS", [0, 0.01]), \
                mock.patch.object(benchmark, "HIT_RATIOS", [0, 1]), \
                mock.patch.object(benchmark, "CLIENTS", [1, 3]), \
                mock.patch.object(benchmark, "PER_CLIENT", 2):
            code, out, _ = self.run_main("--n", "2", "--delay", "0.01", "--out", tmp)
            self.assertEqual(code, 0, out)
            for title in ["① 기본 비교", "② 원본 지연별", "③ 적중률별", "④ 동시 요청", "그래프 저장"]:
                self.assertIn(title, out)
            self.assertNotIn("[경고]", out)
            self.assertEqual(len(os.listdir(tmp)), 3)

    def test_main_rejects_bad_args(self):
        for argv in [("--n", "0"), ("--n", "abc"), ("--delay", "-1"), ("--delay", "nan"), ("--delay", "inf")]:
            code, _, err = self.run_main(*argv)
            self.assertEqual(code, 2, argv)  # argparse 사용법 에러 (traceback 아님)
            self.assertIn("usage", err)

    def test_main_reports_measurement_failure(self):
        # OSError 말고도 측정 중 날 수 있는 에러(스레드가 죽음, Barrier가 깨짐, JSON이 아닌 응답, 모양이 다른 응답)는
        # traceback이 아니라 "측정 실패"로 알린다 (RuntimeError · ValueError는 traceback으로 나오던 것을 재현 후 수정)
        errors = [URLError("연결 거부"), RuntimeError("클라이언트 2명이 요청을 끝내지 못했습니다"),
                  threading.BrokenBarrierError(), json.JSONDecodeError("x", "doc", 0), KeyError("cache")]
        for error in errors:
            with self.subTest(error=type(error).__name__), mock.patch.object(benchmark, "run", side_effect=error):
                code, _, err = self.run_main("--n", "1")
                self.assertEqual(code, 1)
                self.assertIn("측정 실패", err)
                self.assertIn(type(error).__name__, err)

    def test_main_ctrl_c(self):
        with mock.patch.object(benchmark, "run", side_effect=KeyboardInterrupt):
            code, _, err = self.run_main("--n", "1")
        self.assertEqual(code, 130)
        self.assertIn("중단", err)


class StressTest(unittest.TestCase):
    """일반 단위 테스트와 성격이 다른 부하 테스트: 동시 연결 수십 개를 실제로 만든다 (약 1초)"""

    def setUp(self):
        self.addCleanup(setattr, api_server, "redis", api_server.redis)

    def test_many_clients_are_not_refused(self):
        # 연결 대기열(listen backlog) 기본값 5에서는 50명이 동시에 연결하면 WinError 10061(연결 거부)이 났다
        (_, _, with_cache), = benchmark.load(0, [60], 1)
        self.assertEqual((with_cache["count"], with_cache["cache"]), (60, "HIT"))


class ReviewRegressionTest(unittest.TestCase):
    """GPT 리뷰에서 재현한 문제들. 수정 전 코드에서 실패(또는 멈춤)하는 것을 확인한 뒤 고쳤다"""

    def setUp(self):
        self.addCleanup(setattr, api_server, "redis", api_server.redis)

    def run_with_deadline(self, fn, seconds):
        """fn을 별도 스레드에서 실행 → (끝났는지, 결과 또는 예외). 멈추는 버그가 테스트 전체를 멈추게 하지 않도록"""
        box = {}

        def target():
            try:
                box["result"] = fn()
            except BaseException as e:
                box["error"] = e

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(seconds)
        return not t.is_alive(), box

    def test_second_server_failure_does_not_hang(self):
        # 데모 서버 생성이 실패하면(포트 사용 중 등) 아직 serve_forever를 시작하지 않은 Mini Redis 서버에
        # shutdown()을 불러, 서버 루프가 끝났다는 신호를 영원히 기다리며 멈췄다
        before_delay, before_client = api_server.SLOW_DELAY, api_server.redis

        def scenario():
            with mock.patch.object(api_server, "create_demo_server", side_effect=OSError("포트 사용 중")):
                with benchmark._servers(0.5):
                    pass

        finished, box = self.run_with_deadline(scenario, 5)
        self.assertTrue(finished, "서버 정리가 멈췄다")
        self.assertIsInstance(box.get("error"), OSError)  # 원래 에러가 그대로 전달된다
        self.assertEqual(api_server.SLOW_DELAY, before_delay)
        self.assertIs(api_server.redis, before_client)

    def test_servers_restore_redis_client(self):
        # create_demo_server가 바꿔 끼운 전역 Redis 클라이언트(이제 닫힌 서버 주소)가 측정 뒤에도 남아 있었다
        before = api_server.redis
        benchmark.run(1, 0)
        self.assertIs(api_server.redis, before)

    def test_thread_start_failure_releases_started_threads(self):
        # 스레드 3개 중 3번째 시작이 실패하면, 이미 출발선(Barrier)에 선 2개가 30초 동안 기다리다 끝났다
        started = []
        real_start = threading.Thread.start

        def flaky_start(thread):
            if len(started) == 2:
                raise RuntimeError("can't start new thread")
            started.append(thread)
            real_start(thread)

        with fake_server(200, b'{"cache": "HIT"}') as url:
            with mock.patch.object(threading.Thread, "start", flaky_start):
                with self.assertRaises(RuntimeError):
                    benchmark._concurrent(url, 3, 1)
        for t in started:
            t.join(2)
            self.assertFalse(t.is_alive(), "출발한 스레드가 Barrier에서 계속 기다린다")

    def test_concurrent_elapsed_covers_every_request(self):
        # 처리량의 시간은 "모두 출발한 순간 → 마지막 요청이 끝난 순간"이어야 하므로, 어떤 요청 하나보다 짧을 수 없다
        with fake_server(200, b'{"cache": "HIT"}') as url:
            stats = benchmark._concurrent(url, 5, 3)
        self.assertGreaterEqual(stats["elapsed"] * 1000, stats["max"])
        self.assertAlmostEqual(stats["rps"], stats["count"] / stats["elapsed"])

    def test_stats_percentile_definitions(self):
        def stats(values):
            return benchmark._stats([(v, "HIT") for v in values])

        # p50 = 중앙값: 짝수 개면 가운데 두 값의 평균 (전에는 뒤쪽 값 하나를 썼다: [1,2,3,4] → 3)
        self.assertEqual(stats([4, 1, 3, 2])["p50"], 2.5)
        self.assertEqual(stats([3, 1, 2])["p50"], 2)
        self.assertEqual(stats([7])["p50"], 7)
        # p95 = nearest-rank: 정렬해서 ceil(0.95 × n)번째 값 (전에는 n=20일 때 최댓값 20이 나왔다)
        self.assertEqual(stats(range(1, 21))["p95"], 19)
        self.assertEqual(stats(range(1, 101))["p95"], 95)
        self.assertEqual(stats(range(1, 51))["p95"], 48)
        self.assertEqual(stats([7])["p95"], 7)

    def test_measure_rejects_bool_and_float_counts(self):
        # True는 1로, 1.5는 range()에서 TypeError로 새던 것을 다른 함수들과 같은 규칙(_check_count)으로 거부
        for n in [True, 1.5, "3", None, 0, -1]:
            with self.assertRaises(ValueError, msg=n):
                benchmark.measure("http://127.0.0.1:1", n)

    def test_hit_ratio_bypass_is_warned(self):
        # Mini Redis 저장이 실패하면 MISS가 BYPASS가 된다. 적중률 표에 경고가 없으면 캐시 성능으로 오인된다
        def broken_set(self, key, value, ttl):
            raise api_server.RedisUnavailable("저장 실패")

        out = io.StringIO()
        with mock.patch.object(api_server.RedisClient, "set", broken_set), \
                mock.patch.object(benchmark, "SWEEP_DELAYS", [0]), mock.patch.object(benchmark, "HIT_RATIOS", [0.5]), \
                mock.patch.object(benchmark, "CLIENTS", [1]), mock.patch.object(benchmark, "PER_CLIENT", 1), \
                mock.patch("sys.argv", ["benchmark", "--n", "2", "--delay", "0"]), contextlib.redirect_stdout(out):
            benchmark.main()
        self.assertIn("[경고] ③ 적중률별", out.getvalue())

    def test_warn_allows_expected_states(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertTrue(benchmark._warn_if_not_hit("x", [{"cache": "HIT/MISS"}], allowed={"HIT", "MISS"}))
            self.assertFalse(benchmark._warn_if_not_hit("x", [{"cache": "BYPASS/HIT/MISS"}], allowed={"HIT", "MISS"}))
        self.assertEqual(out.getvalue().count("[경고]"), 1)


class EdgeCaseTest(unittest.TestCase):
    """GPT · Gemini 리뷰의 극단 입력 · 자원 정리. 각 케이스는 수정 전 코드에서 재현한 뒤 고쳤다"""

    def setUp(self):
        self.addCleanup(setattr, api_server, "redis", api_server.redis)

    def test_huge_and_special_numbers_are_value_errors(self):
        # math.isfinite(10**10000)는 float 변환에서 OverflowError → 사용자 입력 오류(ValueError)로 통일
        huge, nan, inf = 10 ** 10000, float("nan"), float("inf")
        cases = [
            lambda: benchmark.run(1, huge), lambda: benchmark.run(1, -inf), lambda: benchmark.run(1, inf),
            lambda: benchmark.run(1, nan), lambda: benchmark.run(1, -0.001), lambda: benchmark.run(1, -huge),
            lambda: benchmark.run(1, benchmark.MAX_DELAY + 1),  # time.sleep이 끝나지 않을 만큼 큰 지연
            lambda: benchmark.delay_sweep(1, [0, huge]), lambda: benchmark.hit_ratio(1, huge, [1]),
            lambda: benchmark.hit_ratio(1, 0, [huge]), lambda: benchmark.load(huge, [1], 1),
            lambda: benchmark.load(0, [1], 1.0),
            lambda: benchmark.bar_chart("t", "s", "ms", ["a"], [("x", "on", [huge])]),
            lambda: benchmark.bar_chart("t", "s", "ms", ["a"], [("x", "on", [1.7e308])]),  # 축 계산(× 1.1)이 무한대가 되던 값
            lambda: benchmark.bar_chart("t", "s", "ms", ["a"], [("x", "on", [-inf])]),
            lambda: benchmark.bar_chart("t", "s", "ms", ["a"], [("x", "on", [1])], ref=("r", huge)),
        ]
        for i, case in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(ValueError):
                case()

    def test_normal_numbers_still_accepted(self):
        # 상한을 새로 두었어도 기존에 받던 정상 값(정수 · 실수, 0, 상한 그 자체)은 그대로 받는다
        for delay in [0, 0.0, 1, 0.5, 1e-9, benchmark.MAX_DELAY, float(benchmark.MAX_DELAY)]:
            benchmark._check_delay(delay)
        for values in ([0, 1], [3, 2.5], [10 ** 6, 1e-6], [benchmark._CHART_MAX, 0]):
            ET.fromstring(benchmark.bar_chart("t", "s", "ms", ["a", "b"], [("x", "on", values)]))

    def test_axis_subnormal_and_tiny_values(self):
        # 5e-324 / 4 = 0.0 → log10(0)에서 "expected a positive input" ValueError가 나던 것
        for peak in [5e-324, 1e-310, sys.float_info.min, 1e-300]:
            step, ticks = benchmark._axis(peak)
            self.assertGreater(step, 0, peak)
            self.assertGreaterEqual(step * ticks, peak)
        root = ET.fromstring(benchmark.bar_chart("t", "s", "ms", ["a", "b"], [("x", "on", [5e-324, 0])]))
        self.assertEqual(len(root.findall(f"{SVG}path")), 2)

    def test_warmup_http_error_is_closed_and_raised(self):
        # 캐시 채우기 요청이 500이면 urlopen(...).close()까지 가지 못해 에러 응답의 연결이 열린 채 남았다
        with mock.patch.object(api_server, "get_item_cached", side_effect=RuntimeError("캐시 경로 고장")):
            with self.assertRaises(HTTPError) as cm:
                benchmark.run(1, 0)  # 캐시 미사용 측정(OFF)은 성공하고, 캐시 채우기에서 500
        self.assertEqual(cm.exception.code, 500)  # 원래 에러가 다른 예외로 덮이지 않는다
        self.assertTrue(cm.exception.fp is None or cm.exception.fp.closed)

    def test_every_response_is_closed(self):
        # 측정 요청 · 캐시 채우기 요청 모두 응답 객체를 닫는다 (정상 응답 경로)
        opened, real = [], benchmark.urlopen

        def spy(*args, **kwargs):
            res = real(*args, **kwargs)
            opened.append(res)
            return res

        with mock.patch.object(benchmark, "urlopen", spy):
            benchmark.run(2, 0)
            benchmark.hit_ratio(2, 0, [0.5])
        self.assertEqual(len(opened), 2 + 1 + 2 + 1 + 2)  # run: OFF 2 + 채우기 1 + HIT 2, hit_ratio: 채우기 1 + 2
        self.assertTrue(all(res.closed for res in opened))

    def test_thread_killed_by_base_exception_is_reported(self):
        # except Exception에 안 잡히는 SystemExit로 워커가 모두 죽으면 빈 표본으로 StatisticsError가 나던 것 (Gemini 리뷰, 수정 전 코드로 재현)
        with mock.patch.object(benchmark, "_get", side_effect=SystemExit):
            with self.assertRaises(RuntimeError) as cm:
                benchmark._concurrent("http://unused", 2, 1)
        self.assertIn("2명", str(cm.exception))

    def test_main_thread_barrier_timeout_releases_workers(self):
        # 메인 스레드가 출발선(Barrier)에서 시간 초과(BrokenBarrierError)를 맞는 경로: 30초를 실제로 기다릴 수 없으니,
        # 메인 스레드의 wait만 "시간 초과와 같은 결과(Barrier가 깨짐)"를 내도록 바꿔 끼운다.
        # 워커는 깨진 Barrier에서 바로 풀려나 끝나야 하고, 에러는 그대로 밖으로 나와야 한다 (무한 대기 없음)
        caller, real_barrier, real_start = threading.current_thread(), threading.Barrier, threading.Thread.start
        started = []

        class MainTimesOut(real_barrier):
            def wait(self, timeout=None):
                if threading.current_thread() is caller:
                    self.abort()
                    raise threading.BrokenBarrierError
                return super().wait(timeout)

        def spy_start(thread):
            started.append(thread)
            real_start(thread)

        begin = time.perf_counter()
        with mock.patch.object(threading, "Barrier", MainTimesOut), mock.patch.object(threading.Thread, "start", spy_start):
            with self.assertRaises(threading.BrokenBarrierError):
                benchmark._concurrent("http://unused", 3, 1)
        self.assertLess(time.perf_counter() - begin, 5)
        self.assertEqual(len(started), 3)
        self.assertFalse(any(t.is_alive() for t in started))  # _concurrent가 끝나기 전에 모든 워커를 join했다


class PerformanceComparisonTest(unittest.TestCase):
    """성능 우열 비교 (통합 테스트).
    위 단위 테스트는 요청 수 · 캐시 상태 · 물리적 하한/상한처럼 결정적인 조건만 본다.
    여기서는 "실제로 더 빠른가"를 비교하므로 CPU 부하의 영향을 받을 수 있어서,
    차이가 물리적으로 크게 벌어지는 조건(원본 0.1초 = 요청마다 최소 100ms, 캐시 HIT는 수 ms)과
    표본 20개의 중앙값(튀는 응답 몇 개에 흔들리지 않음)으로 비교한다.
    따로 실행: python -m unittest tests.test_benchmark.PerformanceComparisonTest"""

    DELAY, N = 0.1, 20

    def setUp(self):
        self.addCleanup(setattr, api_server, "redis", api_server.redis)

    def test_cache_hit_faster_than_source(self):
        without_cache, with_cache = benchmark.run(self.N, self.DELAY)
        self.assertLess(with_cache["p50"], without_cache["p50"])

    def test_slower_source_measures_slower(self):
        (_, fast, _), (_, slow, _) = benchmark.delay_sweep(self.N, [0, self.DELAY])
        self.assertGreater(slow["p50"], fast["p50"])

    def test_miss_slower_than_hit(self):
        (_, all_miss), (_, all_hit) = benchmark.hit_ratio(self.N, self.DELAY, [0, 1])
        self.assertGreater(all_miss["p50"], all_hit["p50"])

    def test_cache_throughput_beats_source_cap(self):
        (_, without_cache, with_cache), = benchmark.load(self.DELAY, [10], 2)
        self.assertGreater(with_cache["rps"], without_cache["rps"])  # 캐시는 원본 동시 조회 상한(초당 50건)에 안 걸린다


class SourcePoolTest(unittest.TestCase):
    def test_source_reads_wait_for_free_connection(self):
        # 원본 동시 연결이 5개이므로 10개를 동시에 조회하면 두 번에 나눠 처리된다 → 최소 지연 × 2
        self.addCleanup(setattr, api_server, "SLOW_DELAY", api_server.SLOW_DELAY)
        api_server.SLOW_DELAY = 0.05
        threads = [threading.Thread(target=api_server.fetch_item, args=(1,)) for _ in range(2 * api_server.SOURCE_CONNECTIONS)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertGreaterEqual(time.perf_counter() - start, 0.1 * 0.95)


class MeasureConnectionTest(unittest.TestCase):
    def test_connects_without_timeout_then_reads_with_timeout(self):
        # 연결은 제한 시간 없이 맺어 Windows의 15.6ms 연결 지연을 피하고(측정 잡음의 주원인),
        # 연결된 뒤에는 읽기 제한 시간이 걸려 있어야 응답 없는 서버에서 영원히 기다리지 않는다
        srv = socket.socket()
        self.addCleanup(srv.close)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        conn = benchmark._MeasureConnection("127.0.0.1", srv.getsockname()[1], timeout=0.3)
        self.addCleanup(conn.close)
        with mock.patch.object(conn, "_create_connection", wraps=socket.create_connection) as spy:
            conn.connect()
        self.assertIsNone(spy.call_args.args[1])  # connect에는 제한 시간이 없었다
        self.assertEqual((conn.sock.gettimeout(), conn.timeout), (0.3, 0.3))
        start = time.perf_counter()
        with self.assertRaises((TimeoutError, socket.timeout)):
            conn.sock.recv(1)  # 서버가 아무것도 안 보낸다 → 제한 시간에 끝난다
        self.assertLess(time.perf_counter() - start, 3)


if __name__ == "__main__":
    unittest.main()
