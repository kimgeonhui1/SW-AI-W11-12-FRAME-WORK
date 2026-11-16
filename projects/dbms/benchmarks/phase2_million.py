"""Durable million-row benchmark with repeatable ID and linear-scan queries."""
import argparse
import ctypes
import gc
import json
import os
from pathlib import Path
import platform
import random
import sys
import tempfile
import time
from mini_dbms import Database

def resident_memory_bytes():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb): raise ctypes.WinError(ctypes.get_last_error())
    return counters.WorkingSetSize
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=30)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    if args.rows < 1 or args.repeats < 1 or args.batch_size < 1: parser.error("rows/repeats/batch-size must be positive")
    temporary = tempfile.TemporaryDirectory() if args.data_dir is None else None
    data_dir = Path(temporary.name) if temporary else args.data_dir
    try:
        db = Database(data_dir); table = db.tables["bench_rows"]
        insert_sql = "INSERT INTO bench_rows (lookup_code, payload) VALUES (?, ?)"
        start = time.perf_counter()
        for batch_start in range(0, args.rows, args.batch_size):
            batch_end = min(batch_start + args.batch_size, args.rows)
            params = ((f"code-{i:07d}", f"payload-{i}") for i in range(batch_start, batch_end))
            db.execute_many(insert_sql, params)
        insert_seconds = time.perf_counter() - start
        file_path = data_dir / "bench_rows.rows"
        db = None; table = None; gc.collect()
        recovery_start = time.perf_counter(); db = Database(data_dir); table = db.tables["bench_rows"]; recovery_seconds = time.perf_counter() - recovery_start
        recovered_pairs = list(table.index.items())
        if len(recovered_pairs) != args.rows or [key for key, _ in recovered_pairs] != list(range(1, args.rows + 1)): raise RuntimeError("restart index recovery mismatch")
        rng = random.Random(9217)
        ids = [rng.randrange(1, args.rows + 1) for _ in range(args.repeats)]
        index_times=[]; scan_times=[]; visits=[]
        for row_id in ids:
            start=time.perf_counter(); actual=db.execute("SELECT payload FROM bench_rows WHERE id = ?",(row_id,))["rows"]; index_times.append(time.perf_counter()-start); visits.append(table.index.last_visits)
            start=time.perf_counter(); expected=next(row["payload"] for row,_ in table.rows if row["id"]==row_id); scan_times.append(time.perf_counter()-start)
            if actual != [{"payload":expected}]: raise RuntimeError(f"result mismatch for ID {row_id}")
        print(json.dumps({"rows":args.rows,"batch_size":args.batch_size,"insert_seconds":insert_seconds,"records_per_second":args.rows/insert_seconds,"data_file_bytes":file_path.stat().st_size,"restart_recovery_seconds":recovery_seconds,"recovered_index_rows":len(recovered_pairs),"resident_memory_bytes":resident_memory_bytes(),"environment":{"python":sys.version,"platform":platform.platform(),"os_name":os.name,"tree_max_keys":table.index.max_keys},"query_repeats":args.repeats,"index_seconds_each":index_times,"scan_seconds_each":scan_times,"index_median_seconds":sorted(index_times)[len(index_times)//2],"scan_median_seconds":sorted(scan_times)[len(scan_times)//2],"index_nodes_visited":visits},indent=2))
    finally:
        if temporary: temporary.cleanup()

if __name__ == "__main__": main()
