# [hashtable.py] 직접 구현한 해시 테이블 — 문자열 키 → 값 저장 (파이썬 dict 사용 금지)


class HashTable:
    # 해시 테이블 생성 (capacity = 처음 칸 수)
    def __init__(self, capacity=8):
        raise NotImplementedError("TODO")

    # 저장된 항목 수
    def __len__(self):
        raise NotImplementedError("TODO")

    # 키의 값 조회. 없으면 default
    def get(self, key, default=None):
        raise NotImplementedError("TODO")

    # 키 저장 (이미 있으면 값 덮어쓰기). 부하율이 커지면 리사이즈
    def set(self, key, value):
        raise NotImplementedError("TODO")

    # 키 삭제. 지웠으면 True, 없던 키면 False
    def delete(self, key):
        raise NotImplementedError("TODO")

    # 모든 키 목록
    def keys(self):
        raise NotImplementedError("TODO")
