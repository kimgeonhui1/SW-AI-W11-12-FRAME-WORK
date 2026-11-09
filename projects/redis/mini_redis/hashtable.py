# [hashtable.py] 직접 구현한 해시 테이블 — 문자열 키 → 값 저장 (파이썬 dict 사용 금지)
#
# ■ 구조: 체이닝(separate chaining)
#   buckets = [ [ [key, value], [key, value] ],   ← 0번 칸: 같은 칸으로 모인(충돌한) 항목들의 목록
#               [],                               ← 1번 칸: 비어 있음
#               [ [key, value] ], ... ]
#   1) 키를 해시 함수로 정수로 바꾼다
#   2) 정수 % 칸 수 = 들어갈 칸 번호
#   3) 그 칸의 목록에서 키를 찾는다. 다른 키가 같은 칸에 오면(충돌) 목록에 이어 붙인다
#
# ■ 왜 체이닝인가?
#   충돌이 나도 "그 칸의 목록에 하나 더 붙이기"면 끝이라 삭제가 단순하다.
#   (빈 칸을 찾아 옆으로 이동하는 개방 주소법은, 삭제할 때 "삭제됨" 표시를 따로 관리해야 찾기가 끊기지 않는다)
#
# ■ 리사이즈: 항목 수 / 칸 수(= 부하율)가 0.75를 넘으면 칸을 2배로 늘리고 전부 다시 배치한다.
#   칸에 비해 항목이 많으면 한 칸의 목록이 길어져 찾기가 느려진다(최악 O(n)). 부하율을 낮게 유지하면 평균 O(1)이다.

MAX_LOAD_FACTOR = 0.75

# FNV-1a 해시 상수 (64비트). 짧은 문자열에서도 비트가 고르게 섞이는 단순한 해시 함수다
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
MASK_64 = (1 << 64) - 1


def fnv1a(key):
    """문자열 → 64비트 정수. 같은 키는 항상 같은 값 (파이썬 내장 hash()는 실행할 때마다 값이 바뀐다)"""
    # 키는 문자열만 받는다 (Redis 키도 문자열). 숫자 등이 오면 encode에서 알 수 없는 에러가 나기 전에 원인을 알려 준다
    if not isinstance(key, str):
        raise TypeError(f"키는 문자열이어야 합니다 (받은 타입: {type(key).__name__})")
    h = FNV_OFFSET
    # surrogatepass: "\ud800" 같은 짝 없는 반쪽 문자도 str이라서, 에러 없이 바이트로 바꿔 해시한다
    for byte in key.encode("utf-8", errors="surrogatepass"):
        h ^= byte  # 1) 바이트를 섞고
        h = (h * FNV_PRIME) & MASK_64  # 2) 소수를 곱해 비트를 퍼뜨린 뒤 64비트로 자른다
    return h


class HashTable:
    # 해시 테이블 생성 (capacity = 처음 칸 수)
    def __init__(self, capacity=8):
        # bool은 int의 하위 타입이라(True == 1) 따로 막는다
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            raise ValueError("capacity는 1 이상의 정수여야 합니다")
        self._buckets = [[] for _ in range(capacity)]
        self._size = 0

    # 저장된 항목 수
    def __len__(self):
        return self._size

    # 키의 값 조회. 없으면 default
    def get(self, key, default=None):
        for entry in self._bucket(key):
            if entry[0] == key:
                return entry[1]
        return default

    # 키가 있는지 (값이 None인 키도 "있음"으로 구분하기 위해 get과 따로 둔다)
    def __contains__(self, key):
        return any(entry[0] == key for entry in self._bucket(key))

    # 키 저장 (이미 있으면 값 덮어쓰기). 부하율이 커지면 리사이즈
    def set(self, key, value):
        bucket = self._bucket(key)
        for entry in bucket:
            if entry[0] == key:  # 이미 있는 키 → 값만 바꾼다 (개수는 그대로)
                entry[1] = value
                return
        bucket.append([key, value])
        self._size += 1
        if self._size / len(self._buckets) > MAX_LOAD_FACTOR:
            self._resize(len(self._buckets) * 2)

    # 키 삭제. 지웠으면 True, 없던 키면 False
    def delete(self, key):
        bucket = self._bucket(key)
        for i, entry in enumerate(bucket):
            if entry[0] == key:
                # 칸 안의 순서는 의미가 없으므로, 마지막 항목을 이 자리로 옮기고 끝을 지운다 (뒤 항목을 한 칸씩 당기는 비용 없음)
                bucket[i] = bucket[-1]
                bucket.pop()
                self._size -= 1
                return True
        return False

    # 모든 키 목록 (새 리스트라서, 이 목록을 돌면서 delete해도 안전하다)
    def keys(self):
        return [entry[0] for bucket in self._buckets for entry in bucket]

    # 현재 칸 수 (테스트에서 리사이즈 확인용)
    def capacity(self):
        return len(self._buckets)

    # 키가 들어갈 칸(목록)
    def _bucket(self, key):
        return self._buckets[fnv1a(key) % len(self._buckets)]

    # 칸 수를 바꾸고 모든 항목을 다시 배치한다.
    # 칸 수가 바뀌면 "해시 % 칸 수" 결과도 바뀌어서, 옛 칸에 두면 다시 찾을 수 없기 때문이다
    def _resize(self, new_capacity):
        old = self._buckets
        self._buckets = [[] for _ in range(new_capacity)]
        for bucket in old:
            for key, value in bucket:
                self._buckets[fnv1a(key) % new_capacity].append([key, value])
