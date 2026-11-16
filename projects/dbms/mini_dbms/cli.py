"""Run SQL files or an interactive prompt."""
import argparse
import json
import sys
from pathlib import Path
from .executor import Database
from .parser import SQLParseError, split_script
from .storage import StorageError

def main(argv=None):
    parser = argparse.ArgumentParser(description="Mini DBMS Phase 1")
    parser.add_argument("--data-dir", default="data", help="directory for table files")
    parser.add_argument("sql_file", nargs="?", help="UTF-8 SQL text file; omit for interactive mode")
    args = parser.parse_args(argv)
    try:
        db = Database(args.data_dir)
        if args.sql_file:
            text = Path(args.sql_file).read_text(encoding="utf-8")
            statements = split_script(text)
            for index, sql in enumerate(statements, 1):
                try: print(json.dumps(db.execute(sql), ensure_ascii=False))
                except (SQLParseError, ValueError, StorageError) as exc: print(f"statement {index}: {exc}", file=sys.stderr); return 1
        else:
            while True:
                try: sql = input("mini-db> ")
                except EOFError: break
                if sql.strip().lower() in {"quit", "exit"}: break
                try:
                    for statement in split_script(sql): print(json.dumps(db.execute(statement), ensure_ascii=False))
                except (SQLParseError, ValueError, StorageError) as exc: print(f"error: {exc}", file=sys.stderr)
        return 0
    except (OSError, UnicodeError, StorageError) as exc:
        print(f"database error: {exc}", file=sys.stderr); return 1

if __name__ == "__main__": raise SystemExit(main())
