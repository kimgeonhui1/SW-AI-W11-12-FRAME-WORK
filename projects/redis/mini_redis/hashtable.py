# [hashtable.py] 직접 구현한 해시 테이블 — 문자열 키 → 값 저장 (파이썬 dict 사용 금지)
#
# 설계 문서: projects/redis/Docs/설계.md  2-1 · 3-1 · 4장
#
# ■ 계층에서의 위치: Storage Engine (가장 아래)
#   이 파일은 "키 → 값"만 안다. 만료(TTL) · 락 · HTTP 는 모른다 → 위 계층(store.py · server.py)의 일.
#   그래서 이 클래스 자체는 스레드에 안전하지 않다. 여러 스레드가 쓸 때는 store.py 의 락이 감싼다.
#
# ■ 구조: Separate Chaining (칸마다 리스트)
#   _buckets = [ [],                                  ← 0번 칸: 비어 있음
#                [ ["user:1", 값], ["post:9", 값] ],  ← 1번 칸: 두 키가 같은 칸에 옴(충돌) → 줄 세움
#                [ ["name", 값] ],                    ← 2번 칸
#                ... ]                                (처음 8칸)
#   항목은 [key, value] "리스트" — 덮어쓸 때 entry[1] 만 바꾸면 되도록 튜플이 아닌 리스트로 둔다.
#
# ■ 찾는 순서 (get · set · delete 공통)
#   1) fnv1a(key)  : 키 → 64비트 정수 (FNV-1a, dev 와 같은 모듈 함수)
#   2) _index(key) : 정수 % 칸 수 → 칸 번호
#   3) 그 칸의 리스트를 앞에서부터 보며 같은 key 를 찾는다
#
# ■ 리사이즈: 부하율(항목 수 / 칸 수)이 0.75 를 "넘으면" 칸을 2배로 늘리고 모두 다시 배치한다.
#   칸 수가 바뀌면 "정수 % 칸 수" 가 바뀌므로 모든 항목의 칸 번호를 새로 계산해야 한다 (O(n), 가끔만 일어남).
#   부하율을 0.75 이하로 지키면 한 칸에 줄 선 항목이 평균 1개 아래 → get · set · delete 가 평균 O(1).
#   줄이기(shrink)는 하지 않는다: 지운 뒤 다시 쓰는 경우가 많고 코드만 늘어난다.

MAX_LOAD_FACTOR = 0.75  # 이 값을 넘으면 리사이즈 (정확히 0.75 는 그대로 둔다)

# FNV-1a 64비트 상수 (표준 값, dev 와 같음). 짧은 문자열에서도 비트가 고르게 섞이고, 코드가 몇 줄이면 끝난다
FNV_OFFSET = 0xCBF29CE484222325  # 시작 값
FNV_PRIME = 0x100000001B3  #       곱하는 소수
MASK_64 = (1 << 64) - 1  #         곱한 결과를 64비트로 자르기 (파이썬 정수는 끝없이 커지므로)


# 키 → 64비트 정수 (FNV-1a). 같은 키는 언제 실행해도 같은 값
#   (파이썬 내장 hash() 는 실행할 때마다 문자열 해시가 바뀌어(PYTHONHASHSEED) 테스트 재현이 어렵다)
# 키는 문자열만 받는다: 숫자 · bytes · None 을 넣으면 위 계층의 실수이므로 TypeError 로 바로 알린다.
# "surrogatepass": 짝 없는 반쪽 문자("\ud800")도 파이썬 str 이므로 utf-8 바이트로 바꿀 수 있어야 한다
def fnv1a(key):
    if not isinstance(key, str):
        raise TypeError(f"키는 문자열이어야 합니다 (받은 타입: {type(key).__name__})")
    h = FNV_OFFSET
    for byte in key.encode("utf-8", "surrogatepass"):
        h ^= byte  #                       1) 바이트를 섞고 (XOR)
        h = (h * FNV_PRIME) & MASK_64  #   2) 소수를 곱해 퍼뜨린 뒤 64비트로 자른다 (FNV-1a 는 XOR 이 먼저)
    return h


class HashTable:
    # 해시 테이블 생성 (capacity = 처음 칸 수)
    #   capacity 는 1 이상의 정수만 받는다. 0 이면 "% 칸 수" 에서 0 으로 나누게 되고,
    #   1.5 · "8" 같은 값은 range() 에서 엉뚱한 오류가 나므로 여기서 미리 분명한 ValueError 로 막는다.
    #   True 도 파이썬에서는 int 의 한 종류(= 1)라서 type(...) is int 로 따로 걸러 낸다.
    def __init__(self, capacity=8):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity는 1 이상의 정수여야 합니다")
        self._buckets = [[] for _ in range(capacity)]  # [[]] * n 은 같은 리스트 n 개를 가리켜서 안 된다
        self._size = 0  # 저장된 항목 수 — 매번 세지 않도록 set · delete 에서 직접 늘리고 줄인다

    # 저장된 항목 수 → len(table). 미리 세어 둔 값을 돌려주므로 O(1)
    def __len__(self):
        return self._size

    # 지금 칸 수 (dev 와 같은 메서드 — 리사이즈를 테스트에서 확인할 때 쓴다)
    def capacity(self):
        return len(self._buckets)

    # key in table → 키가 있는지. 값이 None 으로 저장된 키도 "있음" (get 으로는 구별이 안 되므로 따로 둔다)
    # 팀 뼈대에는 없지만 store.py 가 "key in self._data" 로 쓰고 있어 필요하다
    def __contains__(self, key):
        return self._find(key) is not None

    # 키의 값 조회. 없으면 default
    def get(self, key, default=None):
        entry = self._find(key)
        return default if entry is None else entry[1]

    # 키 저장 (이미 있으면 값 덮어쓰기). 부하율이 커지면 리사이즈
    def set(self, key, value):
        bucket = self._buckets[self._index(key)]
        for entry in bucket:
            if entry[0] == key:
                entry[1] = value  # 같은 키 → 값만 바꾼다. 항목 수는 그대로라 리사이즈도 필요 없다
                return
        bucket.append([key, value])  # 새 키 → 칸의 리스트 끝에 붙인다 (충돌이어도 그냥 붙이면 끝)
        self._size += 1
        if self._size / len(self._buckets) > MAX_LOAD_FACTOR:
            self._resize(len(self._buckets) * 2)

    # 키 삭제. 지웠으면 True, 없던 키면 False
    def delete(self, key):
        bucket = self._buckets[self._index(key)]
        for i, entry in enumerate(bucket):
            if entry[0] == key:
                del bucket[i]  # 칸 리스트에서 빼면 끝 — 개방 주소법처럼 "삭제됨" 표시를 남길 필요가 없다
                self._size -= 1
                return True
        return False

    # 모든 키 목록 — 새 리스트를 만들어 돌려준다.
    # 그래서 sweep() 처럼 "키를 돌면서 지우는" 코드가 반복 도중 칸이 바뀌어도 키를 빠뜨리지 않는다
    def keys(self):
        return [entry[0] for bucket in self._buckets for entry in bucket]

    # ── 내부 함수 ─────────────────────────────────────────────────────

    # 키 → 칸 번호 (0 ~ 칸 수 - 1)
    def _index(self, key):
        return fnv1a(key) % len(self._buckets)

    # 키의 항목 [key, value] 를 찾는다. 없으면 None (get · __contains__ 가 함께 쓴다)
    def _find(self, key):
        for entry in self._buckets[self._index(key)]:
            if entry[0] == key:
                return entry
        return None

    # 칸을 new_capacity 개로 늘리고 모든 항목을 새 칸 번호로 다시 넣는다.
    # 항목 리스트([key, value])는 새로 만들지 않고 그대로 옮긴다. 키가 서로 다르므로 같은 키 검사도 필요 없다
    def _resize(self, new_capacity):
        new_buckets = [[] for _ in range(new_capacity)]
        for bucket in self._buckets:
            for entry in bucket:
                new_buckets[fnv1a(entry[0]) % new_capacity].append(entry)
        self._buckets = new_buckets
