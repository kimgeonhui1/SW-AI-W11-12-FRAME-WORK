# [store.py] Mini Redis 본체 — 해시 테이블 위에 저장/조회/삭제 + 만료(TTL) + 동시성 제어


class MiniRedis:
    def __init__(self):
        raise NotImplementedError("TODO")

    # 값 저장. ttl(초)을 주면 그 시간 뒤 만료
    def set(self, key, value, ttl=None):
        raise NotImplementedError("TODO")

    # 값 조회. 없거나 만료됐으면 None (만료된 값은 절대 돌려주지 않음)
    def get(self, key):
        raise NotImplementedError("TODO")

    # 삭제(무효화). 지웠으면 True
    def delete(self, key):
        raise NotImplementedError("TODO")

    # 키가 있는지 (만료된 키는 없는 것)
    def exists(self, key):
        raise NotImplementedError("TODO")

    # 있는 키에 만료 시간(초) 설정. 키가 없으면 False
    def expire(self, key, ttl):
        raise NotImplementedError("TODO")

    # 남은 만료 시간(초). 만료 없음 = -1, 키 없음 = -2 (실제 Redis 규칙)
    def ttl(self, key):
        raise NotImplementedError("TODO")

    # 만료된 키를 메모리에서 정리하고 지운 개수 반환 (서버가 주기적으로 호출)
    def sweep(self):
        raise NotImplementedError("TODO")
