# [benchmark.py] Mini Redis 사용 / 미사용 성능 비교 — 같은 요청을 반복해 응답 시간 측정
#
# 실행: projects/redis 에서  python -m demo.benchmark
#       python -m demo.benchmark --n 10 --rounds 4 --timeout 5
#       python -m demo.benchmark --api http://127.0.0.1:8000     (이미 떠 있는 데모 API를 측정)
#
# ■ 측정 방식
#   1) 워밍업 1회: 첫 요청은 항상 MISS(느린 원본 조회)라서 따로 보내고 평균에서 뺀다
#   2) 묶음(round)마다 cache-on / cache-off 순서를 번갈아 측정한다 (1묶음 on→off, 2묶음 off→on, ...)
#      → 한쪽만 늘 먼저 실행돼 생기는 치우침(예: 시작 직후의 느린 구간)을 줄인다
#   3) 전체 평균·중앙값은 "성공한 요청 하나하나의 시간"으로 계산한다 (묶음별 평균을 다시 평균 내지 않는다)
#
# ■ 두 가지 모드
#   자체 기동(기본): Mini Redis와 데모 API를 빈 포트에 직접 띄워 측정하고, 끝나면(예외가 나도) 둘 다 닫는다
#   외부 URL(--api): 이미 떠 있는 데모 API에 GET만 보낸다. 그 서버를 끄거나 설정·데이터를 바꾸지 않는다
#
# ■ 결과 상태 (STATUS)
#   COMPLETE : 모든 요청 성공 + 비교 조건 일치
#   PARTIAL  : 일부 요청 실패 (성공한 요청만으로 계산한 값)
#   DEGRADED : 비교 조건이 어긋남 (예: cache-on인데 BYPASS·MISS·OFF·unknown, cache-off인데 OFF가 아님)
#   FAILED   : 어느 한쪽 모드에 성공한 요청이 하나도 없음
#   ERROR    : 서버 시작 실패 또는 예상하지 못한 예외
#
# ■ 종료 코드: 0 = 측정을 끝까지 수행 (전체 요청 성공이라는 뜻이 아니다 → STATUS를 본다)
#              1 = FAILED / 2 = ERROR / 3 = 서버 정리 실패 / 130 = 사용자가 중단
#
# ■ 주의: 캐시 미사용이 느린 것은 데모 API가 원본 조회에 넣은 인위적 지연(SLOW_DELAY) 때문이다.
#   이 숫자는 캐시 경로가 동작한다는 관측값이지, Poker 서비스의 성능 측정이 아니다.

import argparse
import http.client
import json
import math
import statistics
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mini_redis.server import create_server
from mini_redis.store import MiniRedis

from . import api_server

KNOWN_STATUSES = ("HIT", "MISS", "OFF", "BYPASS")  # 데모 API가 응답의 "cache" 필드에 넣는 값
STATUS_KEYS = KNOWN_STATUSES + ("unknown",)  # 그 밖의 문자열은 unknown으로 따로 센다
DEFAULT_N = 10  # 묶음 하나에서 모드별 요청 수
DEFAULT_ROUNDS = 4  # 묶음 수
DEFAULT_TIMEOUT = 5.0  # 요청 하나를 기다리는 최대 시간(초)
STOP_WAIT = 5.0  # 자체 기동한 서버 정리를 기다리는 최대 시간(초). 넘으면 "정리 실패"로 보고한다

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ERROR = 2
EXIT_CLEANUP = 3
EXIT_INTERRUPTED = 130


# n, rounds: 1 이상의 정수만. bool은 int의 하위 타입이라(True == 1) 따로 막는다
def _check_positive_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name}은(는) 1 이상의 정수여야 합니다 (받은 값: {value!r})")


# timeout: 0보다 큰 유한한 숫자(초)만. inf / nan / 0 / 음수는 거부
def _check_positive_finite(name, value):
    valid = not isinstance(value, bool) and isinstance(value, (int, float))
    try:
        valid = valid and math.isfinite(value) and value > 0
    except OverflowError:  # float로 바꿀 수 없을 만큼 큰 정수
        valid = False
    if not valid:
        raise ValueError(f"{name}은(는) 0보다 큰 유한한 숫자여야 합니다 (받은 값: {value!r})")


def _is_timeout(exc):
    return isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)


# 요청 n번을 차례로 보내고 결과를 집계 → dict
#   requested / succeeded / failed : 보낸 수 / 성공 수 / 실패 수
#   statuses      : {"HIT", "MISS", "OFF", "BYPASS", "unknown"} 별 성공 응답 수
#   errors        : 실패 이유별 횟수 (timeout, connection, http_500, bad_json, missing_cache, ...)
#   durations_ms  : 성공한 요청 하나하나의 시간(ms). 실패한 요청은 넣지 않는다
#   mean_ms / median_ms : durations_ms의 평균 / 중앙값. 성공이 0건이면 None
#
# 성공 = HTTP 200 + JSON 객체 + 문자열 "cache" 필드. 모르는 문자열은 성공이지만 unknown으로 센다.
# 시간 초과·연결 실패·200이 아닌 응답·JSON이 아닌 응답·cache 필드 누락은 실패 1건으로 세고 다음 요청을 계속한다.
# 그 밖의 예외(코드 버그 등)는 삼키지 않고 그대로 올린다.
#
# clock: 지금 시각(초)을 돌려주는 함수. perf_counter는 컴퓨터 시계를 바꿔도 뒤로 가지 않는(단조 증가) 고해상도 시계다.
#        테스트에서는 가짜 시계를 넣어 시간 계산을 손으로 구한 값과 비교한다 (요청마다 시작 1번, 응답을 다 받은 뒤 1번 부른다)
def measure(url, n, timeout=DEFAULT_TIMEOUT, clock=time.perf_counter):
    _check_positive_int("n", n)
    _check_positive_finite("timeout", timeout)
    durations = []
    statuses = {key: 0 for key in STATUS_KEYS}
    errors = {}

    def fail(kind):
        errors[kind] = errors.get(kind, 0) + 1

    for _ in range(n):
        started = clock()
        try:
            with urlopen(Request(url, method="GET"), timeout=timeout) as res:
                code = res.status
                raw = res.read()
            elapsed_ms = (clock() - started) * 1000  # 본문을 다 받은 시점까지 (JSON 해석 시간은 넣지 않는다)
        except HTTPError as e:  # 4xx / 5xx
            with e:
                fail(f"http_{e.code}")
            continue
        except (URLError, OSError) as e:  # 연결 실패, 시간 초과, 중간에 끊긴 연결
            fail("timeout" if _is_timeout(e) else "connection")
            continue
        except http.client.HTTPException:  # HTTP 형식이 깨진 응답
            fail("bad_http")
            continue

        if code != 200:
            fail(f"http_{code}")
            continue
        try:
            body = json.loads(raw)
        except ValueError:  # JSONDecodeError, UnicodeDecodeError
            fail("bad_json")
            continue
        if not isinstance(body, dict):
            fail("bad_shape")
            continue
        if "cache" not in body:
            fail("missing_cache")
            continue
        cache = body["cache"]
        if not isinstance(cache, str):
            fail("bad_cache_type")
            continue
        statuses[cache if cache in KNOWN_STATUSES else "unknown"] += 1
        durations.append(elapsed_ms)

    return _summary(url, n, durations, statuses, errors)


def _summary(url, requested, durations, statuses, errors):
    return {
        "url": url,
        "requested": requested,
        "succeeded": len(durations),
        "failed": requested - len(durations),
        "statuses": dict(statuses),
        "errors": dict(errors),
        "durations_ms": list(durations),
        "mean_ms": statistics.fmean(durations) if durations else None,
        "median_ms": statistics.median(durations) if durations else None,
    }


# 여러 묶음의 결과를 하나로 합친다. 평균·중앙값은 모든 성공 요청의 개별 시간으로 다시 계산한다
def combine(url, results):
    durations = []
    statuses = {key: 0 for key in STATUS_KEYS}
    errors = {}
    requested = 0
    for r in results:
        requested += r["requested"]
        durations.extend(r["durations_ms"])
        for key in STATUS_KEYS:
            statuses[key] += r["statuses"].get(key, 0)
        for kind, count in r["errors"].items():
            errors[kind] = errors.get(kind, 0) + count
    return _summary(url, requested, durations, statuses, errors)


# 묶음별 실행 순서: 짝수 번째(0부터)는 on→off, 홀수 번째는 off→on
def round_order(rounds):
    _check_positive_int("rounds", rounds)
    return [("on", "off") if i % 2 == 0 else ("off", "on") for i in range(rounds)]


# ── 자체 기동 서버 관리 ──


class _Started:
    def __init__(self, name, server):
        self.name = name
        self.server = server
        self.thread = None  # serve_forever를 돌리는 스레드 (시작 전이면 None)


def _serve(entry):
    entry.thread = threading.Thread(target=entry.server.serve_forever, daemon=True, name="bench-" + entry.name)
    entry.thread.start()
    return f"http://127.0.0.1:{entry.server.server_address[1]}"


def _make_redis_server():
    return create_server(MiniRedis(), port=0)


def _make_api_server(redis_url):
    return api_server.create_demo_server(redis_url, port=0)


# 자체 기동한 서버를 닫고 "정리하지 못한 것" 목록을 돌려준다 (빈 목록 = 깨끗이 정리됨)
#   started          : 시작된(또는 만들다 만) 서버 목록. 나중에 띄운 것부터 닫는다
#   baseline_threads : 서버를 띄우기 전에 살아 있던 스레드. 그 뒤에 생겨 아직 살아 있는 스레드를 "남은 스레드"로 본다
#   wait             : 전체 정리를 기다리는 최대 시간(초). 무한정 기다리지 않는다
def stop_servers(started, baseline_threads=(), wait=STOP_WAIT):
    problems = []
    deadline = time.monotonic() + wait

    def remaining():
        return max(0.0, deadline - time.monotonic())

    for entry in reversed(list(started)):
        thread = entry.thread
        try:
            # shutdown()은 serve_forever가 끝날 때까지 기다리는 함수라서, serve_forever를 시작한 적이 없으면 영원히 멈춘다 → 스레드가 살아 있을 때만 부른다
            # 그래도 멈출 가능성에 대비해 별도 스레드에서 부르고 제한 시간만큼만 기다린다
            if thread is not None and thread.is_alive():
                stopper = threading.Thread(target=entry.server.shutdown, daemon=True, name="bench-stop-" + entry.name)
                stopper.start()
                stopper.join(remaining())
                if stopper.is_alive():
                    problems.append(f"{entry.name}: shutdown이 {wait}초 안에 끝나지 않았습니다")
            entry.server.server_close()  # 소켓을 닫는다 (Mini Redis는 주기 삭제 스레드도 여기서 멈춘다)
        except Exception as e:  # 한 서버 정리가 실패해도 나머지 서버는 계속 정리한다
            problems.append(f"{entry.name}: 정리 중 오류 {type(e).__name__}: {e}")
        if thread is not None:
            thread.join(remaining())
            if thread.is_alive():
                problems.append(f"{entry.name}: 서버 스레드가 끝나지 않았습니다")

    # 요청 처리 스레드·주기 삭제 스레드처럼 서버가 만든 스레드도 끝났는지 제한 시간 안에서 확인한다
    baseline = set(baseline_threads)
    current = threading.current_thread()
    while True:
        left = [t for t in threading.enumerate() if t not in baseline and t is not current and t.is_alive()]
        if not left or remaining() <= 0:
            break
        time.sleep(0.01)
    reported = " ".join(problems)
    for t in left:
        if t.name not in reported:
            problems.append(f"남은 스레드: {t.name}")
    return problems


# ── 측정 실행 ──


def _fmt(ms):
    return "-" if ms is None else f"{ms:.2f}"


def _counts(result):
    return " ".join(f"{key}={result['statuses'][key]}" for key in STATUS_KEYS)


def _condition_warnings(on, off, warmup):
    warnings = []
    if warmup["failed"]:
        warnings.append("워밍업 요청이 실패했습니다 → 첫 측정 요청이 MISS일 수 있습니다")
    s = on["statuses"]
    if s["BYPASS"]:
        warnings.append(f"cache-on에 BYPASS {s['BYPASS']}건: Mini Redis를 쓰지 못해 원본만 조회했습니다 (캐시 사용 수치가 아닙니다)")
    if s["MISS"]:
        warnings.append(f"cache-on에 워밍업 뒤 MISS {s['MISS']}건: 캐시 만료(TTL)·무효화·저장 실패가 섞였습니다")
    if s["OFF"] or s["unknown"]:
        warnings.append(f"비교 조건 불일치: cache-on에 OFF {s['OFF']}건, unknown {s['unknown']}건")
    s = off["statuses"]
    others = {key: s[key] for key in STATUS_KEYS if key != "OFF" and s[key]}
    if others:
        detail = ", ".join(f"{key} {count}건" for key, count in others.items())
        warnings.append(f"비교 조건 불일치: cache-off에 OFF가 아닌 상태 ({detail})")
    return warnings


# 벤치마크 전체 실행 → 보고 dict (exit_code, status, warmup, modes, rounds, warnings, cleanup_problems, error)
#   api_url     : None이면 자체 기동, 주소를 주면 외부 URL 모드(GET만 보내고 그 서버는 건드리지 않는다)
#   out         : 한 줄을 출력하는 함수 (테스트에서 출력 내용을 모은다)
#   measure_fn, make_redis, make_api, stop_wait : 테스트에서 바꿔 끼우는 부분
def run_benchmark(n=DEFAULT_N, rounds=DEFAULT_ROUNDS, timeout=DEFAULT_TIMEOUT, api_url=None, item_id=1,
                  clock=time.perf_counter, out=print, measure_fn=measure,
                  make_redis=_make_redis_server, make_api=_make_api_server, stop_wait=STOP_WAIT):
    _check_positive_int("n", n)
    order = round_order(rounds)
    _check_positive_finite("timeout", timeout)
    _check_positive_int("item_id", item_id)
    if api_url is not None and not (isinstance(api_url, str) and api_url.startswith(("http://", "https://"))):
        raise ValueError("api 주소는 http:// 또는 https:// 로 시작해야 합니다")

    self_hosted = api_url is None
    report = {"mode": "self-hosted" if self_hosted else "external", "exit_code": EXIT_ERROR, "status": "ERROR",
              "warmup": None, "modes": {}, "rounds": [], "warnings": [], "cleanup_problems": [], "error": None}
    started = []
    baseline_threads = set(threading.enumerate())
    previous_client = api_server.redis  # create_demo_server가 바꾸는 모듈 전역 클라이언트. 끝나면 되돌린다
    interrupted = False

    try:
        if self_hosted:
            # 만든 서버는 바로 started에 넣는다 → 다음 단계(두 번째 서버 시작 등)가 실패해도 finally에서 닫힌다
            entry = _Started("redis", make_redis())
            started.append(entry)
            redis_url = _serve(entry)
            entry = _Started("api", make_api(redis_url))
            started.append(entry)
            base = _serve(entry)
        else:
            base = api_url.rstrip("/")
        urls = {"on": f"{base}/items/{item_id}", "off": f"{base}/items/{item_id}?cache=off"}

        out(f"[Mini Redis 캐시 벤치마크] 모드: {report['mode']} / 대상: {base}")
        out(f"묶음 {rounds}개 x 모드별 {n}회, 요청 제한 시간 {timeout}초, 워밍업 1회 별도")

        warmup = measure_fn(urls["on"], 1, timeout=timeout, clock=clock)
        report["warmup"] = warmup
        out(f"워밍업(평균에서 제외): 성공 {warmup['succeeded']} 실패 {warmup['failed']} / {_counts(warmup)} / {_fmt(warmup['mean_ms'])} ms")

        per_mode = {"on": [], "off": []}
        for index, pair in enumerate(order, 1):
            row = {"round": index, "order": pair}
            for mode in pair:
                result = measure_fn(urls[mode], n, timeout=timeout, clock=clock)
                per_mode[mode].append(result)
                row[mode] = result
            report["rounds"].append(row)

        on = combine(urls["on"], per_mode["on"])
        off = combine(urls["off"], per_mode["off"])
        report["modes"] = {"on": on, "off": off}

        out("")
        out("묶음별 (실행 순서 / 평균 ms / 중앙값 ms / 성공/요청)")
        for row in report["rounds"]:
            parts = [f"cache-{mode}: {_fmt(row[mode]['mean_ms'])} / {_fmt(row[mode]['median_ms'])} / {row[mode]['succeeded']}/{row[mode]['requested']}"
                     for mode in ("on", "off")]
            out(f"  {row['round']}묶음 [{'→'.join(row['order'])}]  " + "   ".join(parts))
        out("")
        out("전체 (모든 성공 요청의 개별 시간으로 계산)")
        for mode, result in (("on", on), ("off", off)):
            out(f"  cache-{mode:<3} 요청 {result['requested']} 성공 {result['succeeded']} 실패 {result['failed']}"
                f" | {_counts(result)} | 평균 {_fmt(result['mean_ms'])} ms, 중앙값 {_fmt(result['median_ms'])} ms")
            if result["errors"]:
                out("            실패 이유: " + ", ".join(f"{kind} {count}건" for kind, count in sorted(result["errors"].items())))
        if on["mean_ms"] and off["mean_ms"]:
            out(f"  관측값: cache-off 평균 / cache-on 평균 = {off['mean_ms'] / on['mean_ms']:.1f}배 (합격 기준이 아니라 이번 실행의 관측값)")

        condition = _condition_warnings(on, off, warmup)
        failed_total = on["failed"] + off["failed"]
        partial = [f"요청 {failed_total}건 실패: 위 수치는 성공한 요청만으로 계산했습니다"] if failed_total else []
        report["warnings"] = condition + partial

        if on["succeeded"] == 0 or off["succeeded"] == 0:
            report["status"], report["exit_code"] = "FAILED", EXIT_FAILED
        else:
            flags = (["PARTIAL"] if partial else []) + (["DEGRADED"] if condition else [])
            report["status"], report["exit_code"] = ("+".join(flags) if flags else "COMPLETE"), EXIT_OK
    except KeyboardInterrupt:
        interrupted = True
        report["status"], report["exit_code"], report["error"] = "ERROR", EXIT_INTERRUPTED, "사용자가 중단했습니다"
    except Exception as e:  # 서버 시작 실패, 측정 중 예상하지 못한 예외 → 정상 종료로 처리하지 않는다
        report["status"], report["exit_code"], report["error"] = "ERROR", EXIT_ERROR, f"{type(e).__name__}: {e}"
    finally:
        # 자체 기동한 서버만 닫는다. 외부 URL 모드에서는 started가 비어 있어 아무 서버도 건드리지 않는다
        if started:
            report["cleanup_problems"] = stop_servers(started, baseline_threads, stop_wait)
        if self_hosted:
            api_server.redis = previous_client

    out("")
    for warning in report["warnings"]:
        out("경고: " + warning)
    if report["error"]:
        out("오류: " + report["error"])
    if report["cleanup_problems"]:
        for problem in report["cleanup_problems"]:
            out("정리 실패: " + problem)
        if report["exit_code"] == EXIT_OK:
            report["exit_code"] = EXIT_CLEANUP
    elif self_hosted and not interrupted:
        out("자체 기동한 서버 정리 완료")
    out(f"STATUS: {report['status']} (종료 코드 {report['exit_code']}; 0은 측정을 끝까지 수행했다는 뜻이며 전체 요청 성공을 뜻하지 않습니다)")
    slow = f"{api_server.SLOW_DELAY}초" if self_hosted else "외부 서버 설정값"
    out(f"주의: 원본 조회 지연(SLOW_DELAY = {slow})은 데모 API가 넣은 인위적 지연입니다. Poker 서비스의 성능 측정이 아닙니다.")
    return report


def _arg_positive_int(text):
    try:
        value = int(text)
        _check_positive_int("값", value)
    except ValueError:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다")
    return value


def _arg_positive_finite(text):
    try:
        value = float(text)
        _check_positive_finite("값", value)
    except ValueError:
        raise argparse.ArgumentTypeError("0보다 큰 유한한 숫자여야 합니다")
    return value


# 캐시 사용 / 미사용 결과를 표로 출력 → 종료 코드
def main(argv=None, out=print):
    parser = argparse.ArgumentParser(description="Mini Redis 캐시 사용 / 미사용 성능 비교")
    parser.add_argument("--n", type=_arg_positive_int, default=DEFAULT_N, help="묶음 하나에서 모드별 요청 수")
    parser.add_argument("--rounds", type=_arg_positive_int, default=DEFAULT_ROUNDS, help="묶음 수 (순서를 번갈아 실행)")
    parser.add_argument("--timeout", type=_arg_positive_finite, default=DEFAULT_TIMEOUT, help="요청 제한 시간(초)")
    parser.add_argument("--item", type=_arg_positive_int, default=1, help="측정할 아이템 id")
    parser.add_argument("--api", default=None, help="이미 떠 있는 데모 API 주소 (주면 GET만 보내고 서버는 건드리지 않는다)")
    args = parser.parse_args(argv)
    if args.api is not None and not args.api.startswith(("http://", "https://")):
        parser.error("--api 는 http:// 또는 https:// 로 시작해야 합니다")
    report = run_benchmark(n=args.n, rounds=args.rounds, timeout=args.timeout, api_url=args.api, item_id=args.item, out=out)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
