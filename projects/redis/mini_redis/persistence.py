# [persistence.py] (선택) 서버가 꺼져도 데이터를 지키는 저장 방식 — 스냅샷 저장/복구
#
# ■ 방식: 스냅샷 (실제 Redis의 RDB와 같은 방식)
#   일정 주기마다 저장소 전체를 파일 하나에 저장하고, 서버를 켤 때 그 파일에서 복구한다.
#   - 장점: 파일이 작고 복구가 빠르다
#   - 단점: 마지막 저장 이후에 바뀐 데이터는 서버가 갑자기 꺼지면 잃는다 (명령마다 기록하는 AOF 방식은 이 손실이 작지만 파일이 커진다)
#   Mini Redis는 주로 캐시로 쓰여서, 몇 초~몇십 초치 손실은 원본에서 다시 가져오면 되므로 스냅샷을 택했다.
#
# ■ 파일 모양 (JSON)
#   {"format": 1, "saved_at": 저장 시각(유닉스 초), "entries": [{"key": ..., "value": ..., "ttl": 남은 초 또는 null}, ...]}
#
# ■ TTL: "남은 시간"을 저장하고, 복구할 때 서버가 꺼져 있던 시간만큼 빼서 다시 건다.
#   (저장소는 컴퓨터 시계와 무관한 monotonic 시계를 쓰는데, 이 값은 재시작하면 처음부터 다시 세서 파일에 그대로 남기면 의미가 없다)
#
# ■ 안전한 저장: 임시 파일에 끝까지 쓴 뒤 os.replace로 한 번에 바꿔치기한다.
#   저장 도중 서버가 죽어도 기존 스냅샷 파일은 온전히 남는다 (반쯤 쓰인 파일이 생기지 않는다)

import json
import os
import threading
import time

from .store import MIN_TTL

SNAPSHOT_FORMAT = 1
_wall_clock = time.time  # 테스트에서 "서버가 꺼져 있던 시간"을 흉내 내려고 바꿔 끼울 수 있게 둔다


class SnapshotError(ValueError):
    """스냅샷 파일이 손상되었거나 모양이 다를 때. 이 경우 서버를 띄우지 않아야 기존 파일을 덮어써 날리지 않는다"""


# 저장소의 현재 데이터를 파일로 저장 → 저장한 키 수
def save_snapshot(store, path):
    entries = [{"key": k, "value": v, "ttl": ttl} for k, v, ttl in store.dump()]
    data = {"format": SNAPSHOT_FORMAT, "saved_at": _wall_clock(), "entries": entries}

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # 운영체제 버퍼에만 있지 않고 디스크에 실제로 쓰였는지 확인
        os.replace(tmp_path, path)  # 같은 폴더 안의 이름 바꾸기는 한 번에 일어난다 → 반쯤 바뀐 상태가 없다
    except BaseException:
        # 쓰다가 실패하면(JSON으로 못 바꾸는 값 등) 임시 파일만 지우고, 기존 스냅샷은 그대로 둔다
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return len(entries)


# 파일에서 데이터를 읽어 저장소에 복구 → 복구한 키 수 (파일이 없으면 0: 처음 켜는 서버)
def load_snapshot(store, path):
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("format") != SNAPSHOT_FORMAT or not isinstance(data.get("entries"), list):
            raise SnapshotError("스냅샷 형식이 다릅니다")
        elapsed = max(0.0, _wall_clock() - float(data["saved_at"]))  # 서버가 꺼져 있던 시간 (시계가 뒤로 갔으면 0)
        entries = [(e["key"], e["value"], e["ttl"]) for e in data["entries"]]
    except SnapshotError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise SnapshotError(f"스냅샷 파일을 읽을 수 없습니다: {path} ({e})") from e

    loaded = 0
    for key, value, ttl in entries:
        if ttl is not None:
            ttl -= elapsed
            if ttl < MIN_TTL:
                continue  # 꺼져 있는 동안 만료된 키는 복구하지 않는다
        store.set(key, value, ttl)
        loaded += 1
    return loaded


# interval초마다 스냅샷을 저장하는 스레드 시작 → 멈출 때 쓸 함수 stop() (멈출 때 마지막으로 한 번 더 저장한다)
def start_periodic_snapshot(store, path, interval):
    stop_event = threading.Event()

    def loop():
        while not stop_event.wait(interval):
            try:
                save_snapshot(store, path)
            except Exception as e:  # 저장 실패가 서버를 멈추게 하지 않는다. 다음 주기에 다시 시도
                print(f"[snapshot] 저장 실패: {e}")

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    def stop():
        stop_event.set()
        thread.join()
        save_snapshot(store, path)  # 정상 종료 시점의 데이터까지 남긴다

    return stop
