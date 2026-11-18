# [benchmark.py] Mini Redis 사용 / 미사용 성능 비교 — 같은 요청을 반복해 응답 시간 측정
#
# Mini Redis 서버와 데모 API 서버를 이 프로세스 안에서 빈 포트로 띄운 뒤, 외부 클라이언트처럼 HTTP로 요청한다.
#   - 캐시 미사용: GET /items/{id}?cache=off 를 n번 → 매번 느린 원본 조회
#   - 캐시 사용  : 먼저 한 번 조회해 캐시를 채운 뒤(MISS) GET /items/{id} 를 n번 → 모두 HIT
#
# 측정 네 가지
#   ① 기본 비교       : 원본 지연 --delay 초에서 캐시 미사용 vs 사용
#   ② 원본 지연별      : 원본이 빠르면/느리면 캐시 효과가 어떻게 바뀌나 (캐시가 오히려 손해인 지점까지)
#   ③ 적중률(HIT 비율)별: 실제 트래픽처럼 일부 요청만 HIT일 때 평균 응답 시간
#   ④ 동시 요청        : 클라이언트 여러 명이 동시에 요청할 때 초당 처리량 (원본은 동시 조회 최대 5개로 제한)
#
# 실행: projects/redis 에서  python -m demo.benchmark                      (기본 50번, 원본 지연 0.2초, 약 1분)
#                            python -m demo.benchmark --out docs/benchmark   (그래프 SVG도 저장)

import argparse
import contextlib
import json
import math
import os
import random
import sys
import statistics
import threading
import time
import http.client
import urllib.request
from urllib.error import HTTPError
from xml.sax.saxutils import escape

from demo import api_server
from mini_redis.server import SafeThreadingHTTPServer, create_server
from mini_redis.store import MiniRedis

SWEEP_DELAYS = [0, 0.005, 0.02, 0.05, 0.2]  # ② 원본 지연(초). 0은 "원본이 캐시만큼 빠른" 경우
HIT_RATIOS = [0, 0.5, 0.8, 0.95, 1.0]  # ③ 목표 적중률
CLIENTS = [1, 10, 50]  # ④ 동시 클라이언트 수
PER_CLIENT = 5  # ④ 클라이언트 한 명이 보내는 요청 수


# 요청 한 번 → (응답 시간 ms, 캐시 상태). 응답 본문까지 다 받은 시점까지 잰다
# 측정용 HTTP 연결: TCP 연결은 제한 시간 없이 맺고, 연결된 뒤에만 읽기 제한 시간을 건다.
# Windows에서 제한 시간을 건 소켓은 "논블로킹 connect + select 대기"로 연결하는데, localhost에서도 연결의 약 40%가
# 타이머 단위(약 15.6ms)만큼 늦게 끝났다 (같은 조건에서 제한 시간 없으면 p50 0.3ms · p95 0.6ms, 있으면 p50 1.3ms · p95 15.8ms).
# 캐시 응답이 몇 ms라서 이 지연이 "캐시 사용" 숫자를 흔들던 주원인이었다 (예전 README의 p95 20~40ms).
# 측정 대상은 서버라서 측정 도구의 이 비용은 뺀다. 연결 대상은 이 프로그램이 띄운 localhost 서버다.
# 연결 단계에 제한 시간이 없어도 멈추지 않게, 동시 클라이언트 수를 서버 연결 대기열(128) 이하로 받는다 (load 참고).
class _MeasureConnection(http.client.HTTPConnection):
    def connect(self):
        read_timeout, self.timeout = self.timeout, None
        try:
            super().connect()
        finally:
            self.timeout = read_timeout
        self.sock.settimeout(read_timeout)


class _MeasureHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_MeasureConnection, req)


_opener = urllib.request.build_opener(_MeasureHandler)


# urllib.request.urlopen과 같은 사용법 (테스트가 이 이름을 바꿔 끼워 응답을 모두 닫는지 확인한다)
def urlopen(url, timeout):
    return _opener.open(url, timeout=timeout)


def _get(url):
    start = time.perf_counter()
    try:
        with urlopen(url, timeout=30) as res:
            body = json.loads(res.read())
    except HTTPError as e:
        # 에러 응답(404·500)은 연결을 붙잡은 채로 던져진다. 여기서 닫아 두면 어디서 잡든(측정 실패 출력, 스레드) 연결이 새지 않는다
        e.close()
        raise
    return (time.perf_counter() - start) * 1000, body["cache"]


# (ms, 캐시 상태) 목록 → {"avg", "p50", "p95", "min", "max", "cache"}
def _stats(samples):
    times = sorted(ms for ms, _ in samples)
    return {
        "count": len(times),
        "avg": statistics.fmean(times),
        "p50": statistics.median(times),  # 중앙값: 짝수 개면 가운데 두 값의 평균
        # nearest-rank 방식: 정렬해서 ceil(0.95 × n)번째 값. 이 값 이하인 응답이 95% 이상 (느린 쪽 5% 경계, 가끔 튀는 응답을 보여 준다)
        "p95": times[math.ceil(0.95 * len(times)) - 1],
        "min": times[0],
        "max": times[-1],
        "cache": "/".join(sorted({c for _, c in samples})),  # 측정 중 받은 캐시 상태 (전부 HIT여야 "캐시 사용" 측정이 맞다)
    }


# 요청 n번의 응답 시간(ms) 통계
def measure(url, n):
    _check_count(n, "n")
    return _stats([_get(url) for _ in range(n)])


def _check_count(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name}은(는) 1 이상의 정수여야 합니다")


MAX_DELAY = 3600  # 원본 지연 상한(초). 더 크면 측정이 끝나지 않고, 10**10000 같은 값은 time.sleep에서 OverflowError가 난다
_CHART_MAX = sys.float_info.max / 10  # 축 계산(값 × 1.1)이 float 범위를 넘지 않는 상한


def _is_number_in(value, low, high):
    """bool이 아닌 int/float이고 low 이상 high 이하인지.
    math.isfinite는 아주 큰 정수(10**10000)를 float로 바꾸다 OverflowError가 나므로 쓰지 않는다.
    대신 비교만 한다: 정수와 실수 비교는 변환 없이 정확하고, NaN은 모든 비교가 False, ±Infinity는 범위 밖이라 걸러진다"""
    return not isinstance(value, bool) and isinstance(value, (int, float)) and low <= value <= high


def _check_delay(delay):
    if not _is_number_in(delay, 0, MAX_DELAY):
        raise ValueError(f"delay는 0 이상 {MAX_DELAY} 이하의 숫자(초)여야 합니다")


def _check_list(values, name, check):
    """측정 조건 목록: 비어 있으면 표·그래프를 만들 수 없으므로 거부하고, 항목은 하나씩 check로 검사한다"""
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise ValueError(f"{name}은(는) 목록이어야 합니다")
    values = list(values)
    if not values:
        raise ValueError(f"{name}이(가) 비어 있습니다")
    for value in values:
        check(value)
    return values


def _check_ratio(ratio):
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 <= ratio <= 1:  # NaN도 여기서 걸린다
        raise ValueError("적중률은 0~1 사이 숫자여야 합니다")


# Mini Redis + 데모 API 서버를 띄우고 (API 주소, Mini Redis 저장소)를 넘긴다. 끝나면 서버를 닫고 원본 지연을 되돌린다
@contextlib.contextmanager
def _servers(delay):
    # create_demo_server는 전역 Redis 클라이언트(api_server.redis)를 바꿔 끼운다 → 지연 시간과 함께 원래대로 돌려놓는다
    old_delay, old_client = api_server.SLOW_DELAY, api_server.redis
    api_server.SLOW_DELAY = delay
    store = MiniRedis()
    created, running = [], []  # 만든 서버 / serve_forever를 시작한 서버를 따로 기억한다
    try:
        created.append(create_server(store, port=0))
        created.append(api_server.create_demo_server(f"http://127.0.0.1:{created[0].server_address[1]}", port=0))
        for server in created:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            running.append(server)
        # localhost가 아니라 127.0.0.1: Windows에서 localhost는 IPv6를 먼저 시도해 요청마다 약 0.2초가 더 붙는다
        yield f"http://127.0.0.1:{created[1].server_address[1]}", store
    finally:
        # shutdown()은 serve_forever가 "끝났다"고 알릴 때까지 기다린다. 시작도 안 한 서버에 부르면 영원히 멈춘다
        # (두 번째 서버 생성이 실패했을 때 재현됨) → 시작한 서버만 멈추고, 소켓은 만든 서버 모두 닫는다
        # 연결 풀을 먼저 닫는다: 서버보다 늦게 닫으면 그 사이 풀의 연결을 붙잡은 서버 스레드가 남는다 (Gemini 리뷰)
        if api_server.redis is not old_client:
            api_server.redis.close()  # 바꿔 끼운 클라이언트가 쥐고 있던 연결(연결 풀)을 닫는다
        for server in reversed(running):
            server.shutdown()
        for server in reversed(created):
            server.server_close()
        api_server.SLOW_DELAY = old_delay  # 같은 프로세스의 다른 코드(테스트 등)가 바뀐 지연 시간을 물려받지 않게
        api_server.redis = old_client


# ① 기본 비교 → (캐시 미사용 결과, 캐시 사용 결과)
def run(n, delay, item_id=1):
    # 서버를 띄우기 전에 검사한다 (음수 지연은 원본 조회의 time.sleep에서 에러 → 측정 중 500 응답이 된다)
    _check_count(n, "n")
    _check_delay(delay)
    _check_count(item_id, "item_id")
    if item_id > api_server.ITEM_COUNT:  # 없는 아이템은 404만 재게 된다 → 서버를 띄우기 전에 거부
        raise ValueError(f"item_id는 1~{api_server.ITEM_COUNT} 사이여야 합니다")
    with _servers(delay) as (base, _):
        url = f"{base}/items/{item_id}"
        without_cache = measure(url + "?cache=off", n)
        _get(url)  # 캐시 채우기 (MISS 한 번). _get을 써서 에러 응답이어도 연결을 닫고 에러를 그대로 알린다
        return without_cache, measure(url, n)


# ② 원본 지연별 → [(지연, 미사용 결과, 사용 결과), ...]. 서버는 한 번만 띄우고 지연만 바꾼다
def delay_sweep(n, delays=SWEEP_DELAYS):
    _check_count(n, "n")
    delays = _check_list(delays, "delays", _check_delay)
    results = []
    with _servers(0) as (base, _):
        url = f"{base}/items/1"
        for delay in delays:
            api_server.SLOW_DELAY = delay
            without_cache = measure(url + "?cache=off", n)
            _get(url)  # 캐시 채우기
            results.append((delay, without_cache, measure(url, n)))
    return results


# ③ 적중률별 → [(목표 적중률, 결과 + "hit": 실제 적중률), ...]
# HIT 요청은 캐시된 아이템 1번, MISS 요청은 아이템 2번. MISS 직전에 2번의 캐시를 지워서 매번 진짜 MISS(원본 조회 + 캐시 저장)가 되게 한다
def hit_ratio(n, delay, ratios=HIT_RATIOS):
    _check_count(n, "n")
    _check_delay(delay)
    ratios = _check_list(ratios, "ratios", _check_ratio)
    rng = random.Random(0)  # 같은 순서로 섞어 매번 같은 조건으로 측정
    results = []
    with _servers(delay) as (base, store):
        hit_url, miss_id = f"{base}/items/1", 2
        _get(hit_url)  # HIT용 아이템 캐시 채우기
        for ratio in ratios:
            hits = round(n * ratio)
            plan = [True] * hits + [False] * (n - hits)
            rng.shuffle(plan)  # HIT와 MISS가 섞여 들어오는 실제 트래픽처럼
            samples = []
            for is_hit in plan:
                if is_hit:
                    samples.append(_get(hit_url))
                else:
                    # 지우는 시간은 측정에 넣지 않는다 (_get 바깥)
                    store.delete(api_server.cache_key(miss_id, api_server.current_version(miss_id)))
                    samples.append(_get(f"{base}/items/{miss_id}"))
            stats = _stats(samples)
            stats["hit"] = sum(cache == "HIT" for _, cache in samples) / n
            results.append((ratio, stats))
    return results


# 클라이언트 clients명이 동시에 per_client번씩 요청 → 결과 + "rps"(초당 처리 요청 수)
def _concurrent(url, clients, per_client):
    samples, errors, finished = [], [], []
    lock = threading.Lock()
    clock = {}
    # 모든 클라이언트가 준비된 뒤 한꺼번에 출발 (스레드 생성 시간이 섞이지 않게).
    # action: 마지막 스레드가 도착해 모두가 풀려나기 "직전"에 시작 시각을 잰다. 메인 스레드가 풀려난 뒤에 재면
    #         그사이 이미 시작된 요청 시간이 빠져 처리량이 부풀려진다
    # timeout: 스레드 하나가 끝내 출발선에 못 오면 영원히 기다리지 않고 BrokenBarrierError로 측정 실패를 알린다
    ready = threading.Barrier(clients + 1, action=lambda: clock.setdefault("start", time.perf_counter()), timeout=30)

    def worker():
        try:
            ready.wait()
            got = [_get(url) for _ in range(per_client)]
        except Exception as e:  # 스레드 안의 에러는 그냥 두면 사라지므로 모아서 측정 실패로 알린다
            with lock:
                errors.append(e)
            return
        done = time.perf_counter()  # 이 클라이언트의 마지막 요청이 끝난 시각 (메인 스레드가 join에서 늦게 깨어나도 영향 없음)
        with lock:
            samples.extend(got)
            finished.append(done)

    threads = []
    try:
        for _ in range(clients):
            t = threading.Thread(target=worker)
            t.start()
            threads.append(t)
        ready.wait()
    except BaseException:
        # 스레드 시작 실패 등으로 출발하지 못하면, 이미 출발선에 선 스레드를 바로 풀어 준다 (30초 대기 없이 끝나게)
        ready.abort()
        for t in threads:
            t.join()
        raise
    for t in threads:
        t.join()
    if errors:
        raise errors[0]  # 첫 에러만 알린다 (에러 응답의 연결은 _get에서 이미 닫혔다)
    if len(finished) != clients:
        # except Exception에 안 잡히는 BaseException(SystemExit 등)으로 죽은 스레드는 errors에도 finished에도 없다.
        # 결과가 빠진 채 숫자를 내면 안 되고, 전부 죽었으면 빈 표본으로 _stats가 StatisticsError를 냈다 (Gemini 리뷰, 수정 전 코드로 재현)
        raise RuntimeError(f"클라이언트 {clients - len(finished)}명이 요청을 끝내지 못했습니다")
    stats = _stats(samples)
    stats["elapsed"] = max(finished) - clock["start"]  # 모두 출발한 순간 → 마지막 요청이 끝난 순간
    stats["rps"] = len(samples) / stats["elapsed"]
    return stats


# ④ 동시 요청 → [(클라이언트 수, 미사용 결과, 사용 결과), ...]
def load(delay, clients_list=CLIENTS, per_client=PER_CLIENT):
    _check_delay(delay)
    _check_count(per_client, "per_client")
    clients_list = _check_list(clients_list, "clients_list", lambda c: _check_count(c, "clients"))
    # 측정 연결은 제한 시간 없이 맺는다(_MeasureConnection). 동시 연결이 서버 대기열(listen backlog)을 넘으면 OS가 연결 요청을
    # 버려 OS 재시도 시간(리눅스 약 2분)만큼 기다릴 수 있어서, 대기열 크기를 넘는 클라이언트 수는 받지 않는다
    limit = SafeThreadingHTTPServer.request_queue_size
    if max(clients_list) > limit:
        raise ValueError(f"clients는 서버 연결 대기열 크기({limit}) 이하여야 합니다")
    results = []
    with _servers(delay) as (base, _):
        url = f"{base}/items/1"
        _get(url)  # 캐시 채우기
        for clients in clients_list:
            results.append((clients, _concurrent(url + "?cache=off", clients, per_client),
                            _concurrent(url, clients, per_client)))
    return results


# ───────── 그래프 (SVG) ─────────
# 외부 라이브러리 없이 막대그래프를 SVG 글자로 직접 만든다. 다크 모드에서는 prefers-color-scheme으로 색을 바꾼다
_STYLE = """<style>
.bg{fill:#fcfcfb}.t1{fill:#0b0b0b}.t2{fill:#52514e}.grid{stroke:#e4e3df}.axis{stroke:#8a8984}
.s-on{fill:#2a78d6}.s-off{fill:#eb6834}.ref{stroke:#eb6834}
text{font-family:system-ui,-apple-system,"Malgun Gothic","Apple SD Gothic Neo",sans-serif}
@media (prefers-color-scheme:dark){.bg{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}.grid{stroke:#383835}
.axis{stroke:#6f6e69}.s-on{fill:#3987e5}.s-off{fill:#d95926}.ref{stroke:#d95926}}
</style>"""


def _axis(peak):
    """y축 눈금 (간격, 개수). 간격은 1·2·5 × 10의 거듭제곱이라 0, 50, 100처럼 깔끔하고, 맨 위 눈금은 peak 이상 (2~4칸)"""
    if peak <= 0:
        return 1, 1
    # subnormal(5e-324 등)은 4로 나누면 0.0이 되어 log10(0) 에러 → 가장 작은 정상 float로 바닥을 둔다
    rough = max(peak / 4, sys.float_info.min)
    exp = 10 ** math.floor(math.log10(rough))
    step = next((m * exp for m in (1, 2, 5, 10) if m * exp >= rough), 10 * exp)
    return step, max(1, math.ceil(peak / step - 1e-9))  # 1e-9: 300 / 100 = 3.0000000000000004 같은 실수 오차로 한 칸 더 생기지 않게


def _fmt(value):
    if value == int(value):
        return f"{value:,.0f}"  # 눈금 0, 100처럼 정수면 소수점 없이
    return f"{value:.1f}" if value < 10 else f"{value:,.0f}"


# groups: x축 이름들, series: [(범례 이름, "on"/"off", 값 목록)], ref: (이름, 값) 가로 점선 기준선
def bar_chart(title, subtitle, unit, groups, series, ref=None):
    if not groups or not series:
        raise ValueError("그래프에 그릴 묶음과 계열이 필요합니다")
    for name, slot, values in series:
        if slot not in ("on", "off"):
            raise ValueError(f"계열 색은 on/off만 있습니다: {slot!r}")
        if len(values) != len(groups):
            raise ValueError(f"{name}: 값 {len(values)}개와 묶음 {len(groups)}개 수가 다릅니다")
    values_to_check = [v for _, _, values in series for v in values] + ([ref[1]] if ref else [])
    if not all(_is_number_in(v, 0, _CHART_MAX) for v in values_to_check):
        raise ValueError("그래프 값은 0 이상의 유한한 숫자여야 합니다 (너무 큰 값 제외)")
    width, height = 680, 340
    left, right, top, bottom = 64, 20, 88, 44
    pw, ph = width - left - right, height - top - bottom
    peak = max([v for _, _, values in series for v in values] + ([ref[1]] if ref else []))
    step, ticks = _axis(peak * 1.1)  # 1.1: 맨 위 막대의 값 글자가 잘리지 않게 여유
    y_max = step * ticks

    def y(v):
        return top + ph - v / y_max * ph

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
           f'role="img" aria-label="{escape(title)}">', f"<title>{escape(title)}</title>", _STYLE,
           f'<rect class="bg" width="{width}" height="{height}" rx="8"/>',
           f'<text class="t1" x="{left}" y="30" font-size="16" font-weight="600">{escape(title)}</text>',
           f'<text class="t2" x="{left}" y="50" font-size="12">{escape(subtitle)}</text>',
           f'<text class="t2" x="{left - 8}" y="{top - 12}" font-size="11" text-anchor="end">{escape(unit)}</text>']
    for i in range(ticks + 1):  # 가로 눈금선 (흐리게)
        v = step * i
        out.append(f'<line class="{"axis" if i == 0 else "grid"}" x1="{left}" x2="{width - right}" '
                   f'y1="{y(v):.1f}" y2="{y(v):.1f}" stroke-width="1"/>')
        out.append(f'<text class="t2" x="{left - 8}" y="{y(v) + 4:.1f}" font-size="11" text-anchor="end">{_fmt(v)}</text>')

    group_w = pw / len(groups)
    bar_w = min(40, group_w * 0.7 / len(series))
    gap = 2  # 같은 묶음 막대 사이 틈
    for gi, label in enumerate(groups):
        cx = left + group_w * (gi + 0.5)
        x0 = cx - (len(series) * bar_w + (len(series) - 1) * gap) / 2
        for si, (name, slot, values) in enumerate(series):
            v = values[gi]
            x, h = x0 + si * (bar_w + gap), max(v / y_max * ph, 1)  # 0에 가까워도 1px은 보이게
            r = min(4, bar_w / 2, h)  # 위쪽 모서리만 둥글게 (아래는 기준선에 붙인다)
            base, top_y = top + ph, top + ph - h
            out.append(f'<path class="s-{slot}" d="M{x:.1f},{base} V{top_y + r:.1f} Q{x:.1f},{top_y:.1f} {x + r:.1f},{top_y:.1f} '
                       f'H{x + bar_w - r:.1f} Q{x + bar_w:.1f},{top_y:.1f} {x + bar_w:.1f},{top_y + r:.1f} V{base} Z">'
                       f"<title>{escape(name)} · {escape(label)}: {_fmt(v)} {escape(unit)}</title></path>")
            out.append(f'<text class="t2" x="{x + bar_w / 2:.1f}" y="{top_y - 5:.1f}" font-size="10.5" '
                       f'text-anchor="middle">{_fmt(v)}</text>')
        out.append(f'<text class="t2" x="{cx:.1f}" y="{top + ph + 20}" font-size="12" text-anchor="middle">{escape(label)}</text>')

    if ref:
        ry = y(ref[1])
        out.append(f'<line class="ref" x1="{left}" x2="{width - right}" y1="{ry:.1f}" y2="{ry:.1f}" stroke-width="2" stroke-dasharray="6 4"/>')
        out.append(f'<text class="t2" x="{width - right}" y="{ry - 6:.1f}" font-size="11" text-anchor="end">'
                   f"{escape(ref[0])} {_fmt(ref[1])} {escape(unit)}</text>")

    if len(series) > 1:  # 범례: 계열이 둘 이상일 때만 (하나면 제목이 설명한다)
        lx = left
        for name, slot, _ in series:
            out.append(f'<rect class="s-{slot}" x="{lx}" y="62" width="12" height="12" rx="3"/>')
            out.append(f'<text class="t1" x="{lx + 18}" y="72" font-size="12">{escape(name)}</text>')
            lx += 18 + 13 * len(name) + 20
    out.append("</svg>")
    return "\n".join(out)


# 세 그래프를 out_dir에 저장 → 저장한 파일 경로 목록
def write_charts(out_dir, n, delay, sweep, ratios, loads, baseline_ms):
    os.makedirs(out_dir, exist_ok=True)
    charts = {
        "delay.svg": bar_chart(
            "원본 지연별 응답 시간 (중앙값)", f"요청 {n}번씩 순차 · 낮을수록 좋음", "ms",
            [f"{d * 1000:g}ms" for d, _, _ in sweep],
            [("캐시 미사용", "off", [w["p50"] for _, w, _ in sweep]), ("캐시 사용(HIT)", "on", [c["p50"] for _, _, c in sweep])]),
        "hit-ratio.svg": bar_chart(
            "적중률별 평균 응답 시간 (캐시 사용)", f"원본 지연 {delay * 1000:g}ms · 요청 {n}번 · 낮을수록 좋음", "ms",
            [f"{r['hit'] * 100:.0f}%" for _, r in ratios],
            [("캐시 사용", "on", [r["avg"] for _, r in ratios])], ref=("캐시 미사용 평균", baseline_ms)),
        "concurrency.svg": bar_chart(
            "동시 클라이언트 수별 처리량", f"원본 지연 {delay * 1000:g}ms · 원본 동시 조회 최대 {api_server.SOURCE_CONNECTIONS}개 · 높을수록 좋음",
            "요청/초", [f"{c}명" for c, _, _ in loads],
            [("캐시 미사용", "off", [w["rps"] for _, w, _ in loads]), ("캐시 사용(HIT)", "on", [c["rps"] for _, _, c in loads])]),
    }
    paths = []
    for name, svg in charts.items():
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        paths.append(path)
    return paths


# 결과를 표로 출력 (--out이 있으면 그래프도 저장)
def main():
    parser = argparse.ArgumentParser(description="Mini Redis 사용/미사용 성능 비교")
    parser.add_argument("--n", type=int, default=50, help="측정 한 번에 보내는 요청 수")
    parser.add_argument("--delay", type=float, default=0.2, help="원본 조회 지연(초)")
    parser.add_argument("--out", help="그래프 SVG를 저장할 폴더 (없으면 표만 출력)")
    args = parser.parse_args()
    try:
        _check_count(args.n, "--n")
        _check_delay(args.delay)
    except ValueError as e:  # 잘못된 --n / --delay는 traceback 대신 사용법과 함께 알려 준다
        parser.error(str(e))
    try:
        _report(args)
    except KeyboardInterrupt:  # 서버는 _servers의 finally에서 이미 닫혔다
        parser.exit(130, "\n측정을 중단했습니다\n")
    # 연결 거부·시간 초과(URLError 포함)·그래프 폴더를 만들 수 없음(OSError), 클라이언트 스레드가 죽음·Barrier가 깨짐(RuntimeError),
    # 측정 대상이 JSON이 아니거나(ValueError) 약속과 다른 모양(KeyError)인 응답 → traceback 대신 "측정 실패"로 알린다
    except (OSError, RuntimeError, ValueError, KeyError) as e:
        parser.exit(1, f"\n측정 실패: {type(e).__name__}: {e}\n")


def _warn_if_not_hit(label, results, allowed=("HIT",)):
    """측정에 예상 밖 캐시 상태(예: Mini Redis 장애로 BYPASS)가 섞였으면 그 숫자는 캐시 성능이 아니다 → 눈에 띄게 경고"""
    bad = [r["cache"] for r in results if not set(r["cache"].split("/")) <= set(allowed)]
    if bad:
        print(f"[경고] {label}: {'/'.join(sorted(allowed))} 외의 응답이 섞였습니다 ({', '.join(bad)}). 이 결과는 믿을 수 없습니다")
    return not bad


def _report(args):
    def section(title):
        print(f"\n■ {title}", flush=True)

    section(f"① 기본 비교: 요청 {args.n}번, 원본 조회 지연 {args.delay}초 (단위: ms)")
    without_cache, with_cache = run(args.n, args.delay)
    print(f"{'':14}{'평균':>9}{'p50':>9}{'p95':>9}{'최소':>9}{'최대':>9}   캐시 상태")
    for label, r in [("캐시 미사용", without_cache), ("캐시 사용", with_cache)]:
        print(f"{label:<12}{r['avg']:>9.1f}{r['p50']:>9.1f}{r['p95']:>9.1f}{r['min']:>9.1f}{r['max']:>9.1f}   {r['cache']}")
    print(f"→ 캐시 사용 시 평균 {without_cache['avg'] / with_cache['avg']:.1f}배 빠름")
    _warn_if_not_hit("① 기본 비교", [with_cache])

    # 중앙값으로 비교: 캐시 쪽은 몇 ms라서, 가끔 튀는 응답 몇 개가 평균을 크게 흔든다 (평균은 참고로 함께 출력)
    section(f"② 원본 지연별 응답 시간 (요청 {args.n}번씩, 단위: ms)")
    sweep = delay_sweep(args.n, SWEEP_DELAYS)
    print(f"{'원본 지연':<10}{'미사용 p50':>12}{'사용 p50':>10}{'p50 배수':>10}{'미사용 평균':>12}{'사용 평균':>10}")
    for delay, w, c in sweep:
        print(f"{delay * 1000:>6g}ms  {w['p50']:>12.1f}{c['p50']:>10.1f}{w['p50'] / c['p50']:>9.1f}×"
              f"{w['avg']:>12.1f}{c['avg']:>10.1f}")
    _warn_if_not_hit("② 원본 지연별", [c for _, _, c in sweep])

    section(f"③ 적중률별 평균 응답 시간 (원본 지연 {args.delay}초, 요청 {args.n}번, 단위: ms)")
    ratios = hit_ratio(args.n, args.delay, HIT_RATIOS)
    print(f"{'실제 적중률':<10}{'평균':>9}{'p50':>9}{'p95':>9}{'미사용 대비':>12}")
    for _, r in ratios:
        print(f"{r['hit'] * 100:>8.0f}%  {r['avg']:>9.1f}{r['p50']:>9.1f}{r['p95']:>9.1f}{without_cache['avg'] / r['avg']:>11.1f}×")

    _warn_if_not_hit("③ 적중률별", [r for _, r in ratios], allowed=("HIT", "MISS"))

    section(f"④ 동시 요청 (원본 지연 {args.delay}초, 원본 동시 조회 최대 {api_server.SOURCE_CONNECTIONS}개, 클라이언트당 {PER_CLIENT}번)")
    loads = load(args.delay, CLIENTS, PER_CLIENT)
    print(f"{'클라이언트':<8}{'미사용 요청/초':>14}{'p95(ms)':>10}{'사용 요청/초':>14}{'p95(ms)':>10}{'배수':>9}")
    for clients, w, c in loads:
        print(f"{clients:>6}명  {w['rps']:>14.1f}{w['p95']:>10.1f}{c['rps']:>14.1f}{c['p95']:>10.1f}{c['rps'] / w['rps']:>8.1f}×")
    _warn_if_not_hit("④ 동시 요청", [c for _, _, c in loads])

    if args.out:
        paths = write_charts(args.out, args.n, args.delay, sweep, ratios, loads, without_cache["avg"])
        section("그래프 저장")
        for path in paths:
            print(path)


if __name__ == "__main__":
    main()
