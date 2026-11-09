# [persistence.py] (선택) 서버가 꺼져도 데이터를 지키는 저장 방식 — 스냅샷 저장/복구


# 저장소의 현재 데이터를 파일로 저장
def save_snapshot(store, path):
    raise NotImplementedError("TODO")


# 파일에서 데이터를 읽어 저장소에 복구
def load_snapshot(store, path):
    raise NotImplementedError("TODO")
