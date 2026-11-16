"""Append-only JSONL storage; B+Tree offsets are rebuilt from the file at startup."""
import hashlib, json, os, threading
from pathlib import Path
from .bptree import BPlusTree
from .schema import MAX_RECORD_BYTES

class StorageError(RuntimeError): pass

class TableFile:
    def __init__(self, root, name, schema, tree_max_keys=31):
        self.path=Path(root)/f"{name}.rows"; self.path.parent.mkdir(parents=True,exist_ok=True)
        self.schema=schema; self.lock=threading.RLock(); self.rows=[]; self.next_id=1; self.failed=False
        self.index=BPlusTree(tree_max_keys); self._recover()
    def _validate_row(self,row):
        if not isinstance(row,dict) or set(row)!={"id",*self.schema}: raise ValueError("record columns do not match schema")
        if not isinstance(row["id"],int) or isinstance(row["id"],bool) or row["id"]<1: raise ValueError("invalid record id")
        for name,kind in self.schema.items():
            value=row[name]; valid=isinstance(value,str) if kind=="TEXT" else isinstance(value,int) and not isinstance(value,bool)
            if not valid: raise ValueError(f"invalid {kind} value in {name}")
    def _encode(self,row):
        body=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
        record=json.dumps({"row":row,"sha256":hashlib.sha256(body).hexdigest()},ensure_ascii=False,separators=(",",":")).encode("utf-8")+b"\n"
        if len(record)>MAX_RECORD_BYTES: raise StorageError("Record too large")
        return record
    def _recover(self):
        if not self.path.exists(): return
        seen=set()
        with self.path.open("rb") as f:
            offset=0
            for line_no,raw in enumerate(f,1):
                if not raw.endswith(b"\n"): raise StorageError(f"Incomplete record at line {line_no}; refusing automatic repair")
                if len(raw)>MAX_RECORD_BYTES: raise StorageError(f"Record too large at line {line_no}")
                try:
                    record=json.loads(raw); row=record["row"]; body=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
                    if hashlib.sha256(body).hexdigest()!=record["sha256"]: raise ValueError("checksum mismatch")
                    self._validate_row(row)
                    if row["id"] in seen: raise ValueError("duplicate id")
                except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc: raise StorageError(f"Invalid record at line {line_no}") from exc
                seen.add(row["id"]); self.rows.append((row,offset))
                try: self.index.insert(row["id"],offset)
                except (TypeError,ValueError) as exc: raise StorageError(f"Cannot rebuild ID index at line {line_no}") from exc
                offset+=len(raw)
        self.next_id=max(seen,default=0)+1
    def _ensure_ready(self):
        if self.failed: raise StorageError("Table unavailable after uncertain file/index operation; reopen for recovery")
    def append_many(self,records):
        records=list(records)
        if not records: return []
        with self.lock:
            self._ensure_ready(); encoded=[]; next_id=self.next_id
            for values in records:
                row={"id":next_id,**values}; self._validate_row(row); encoded.append((row,self._encode(row))); next_id+=1
            offsets=[]
            try:
                with self.path.open("ab") as f:
                    offset=f.tell()
                    for row,raw in encoded: offsets.append(offset); f.write(raw); offset+=len(raw)
                    f.flush(); os.fsync(f.fileno())
                # A durable file record not yet indexed is recovered by the next startup scan.
                for (row,_),offset in zip(encoded,offsets): self.index.insert(row["id"],offset)
                self.rows.extend((row,offset) for (row,_),offset in zip(encoded,offsets)); self.next_id=next_id
            except (OSError,ValueError,TypeError) as exc:
                self.failed=True; raise StorageError("File or index update uncertain; table disabled until reopened for recovery") from exc
            return [row["id"] for row,_ in encoded]
    def append(self,values): return self.append_many([values])[0]
    def _read_offset(self,offset):
        with self.path.open("rb") as f: f.seek(offset); raw=f.readline(MAX_RECORD_BYTES+1)
        if not raw.endswith(b"\n") or len(raw)>MAX_RECORD_BYTES: raise StorageError("Indexed record is incomplete")
        try:
            record=json.loads(raw); row=record["row"]; body=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
            if hashlib.sha256(body).hexdigest()!=record["sha256"]: raise ValueError("checksum mismatch")
            self._validate_row(row); return row
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc: raise StorageError("Indexed record failed validation") from exc
    def select(self,columns,where=None):
        with self.lock:
            self._ensure_ready()
            if where is not None and where[0]=="id":
                offset=self.index.get(where[1])
                if offset is None: return []
                return [{c:self._read_offset(offset)[c] for c in columns}]
            return [{c:row[c] for c in columns} for row,_ in self.rows if where is None or row.get(where[0])==where[1]]
