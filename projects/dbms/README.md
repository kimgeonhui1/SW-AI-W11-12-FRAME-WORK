# Mini DBMS Phase 1

Python standard-library implementation of the WEEK11-12 SQL-file → CLI → parser → executor → per-table file path.

## Run

From this directory:

```powershell
python -m mini_dbms.cli --data-dir .\data .\sample.sql
python -m unittest discover -s tests -v
```

Tables and column types are fixed in `mini_dbms/schema.py`; CREATE TABLE, UPDATE, and DELETE are unsupported. Each INSERT appends one checksummed UTF-8 JSON record to its table-specific `.rows` file and calls flush/fsync before reporting the ID. Startup validates records and rebuilds the in-memory row offsets and next ID. SELECT supports projections, `*`, and equality filters; filters currently scan rows. A malformed or partial record stops startup without silently discarding data.

SQL files may contain multiple statements. A failure reports the statement number; earlier statements remain applied. This is not a file-wide transaction. Phase 2 can replace scan-based lookup while preserving the parser/executor boundary.

## Phase 3 SQL API

Start after the database files have been recovered:

```powershell
python -m mini_dbms.server --data-dir .\data --host 127.0.0.1 --port 8765 --workers 4 --queue-size 32
```

`Database` is constructed before the HTTP server binds its socket, so malformed storage or incomplete B+Tree rebuild prevents the service from accepting requests. The server uses a fixed `ThreadPoolExecutor`; at most `workers + queue-size` accepted requests may be active or queued. Excess requests receive HTTP 503 (`server_busy`). Shutdown stops accepting new sockets and waits for accepted worker jobs to finish.

### Request

`POST /sql`, `Content-Type: application/json`, maximum body 64 KiB:

```json
{"sql":"SELECT id, display_name FROM players WHERE id = ?","params":[1]}
```

`params` is optional and defaults to `[]`. Only one SQL statement is accepted. SQL language and validation are provided by the existing Phase 1 parser/executor.

### Responses

- `200`: `{"ok":true,"result":{"rows":[...]}}` or `{"ok":true,"result":{"insertedId":1}}`
- `400`: malformed JSON, request shape, or SQL (`invalid_sql_request`)
- `404`/`405`: unsupported route or method
- `411`/`413`: missing/oversize request body
- `503`: bounded work queue full (`server_busy`) or table unavailable (`storage_unavailable`)
- `500`: unexpected execution failure; internal exception details are not exposed

### Atomic append-once API

`POST /sql/insert-once` accepts the same SQL and parameter fields as `/sql`, plus `keyColumn`:

```json
{"sql":"INSERT INTO guest_users (user_id, token_hash, display_name, created_at) VALUES (?, ?, ?, ?)","params":["guest-id","sha256-token","Guest","2026-11-12T00:00:00Z"],"keyColumn":"token_hash"}
```

The DBMS holds the target table lock while it scans for `keyColumn`, compares the full row, and either returns its existing ID or durably appends one row. Exact retries return `created:false`; reusing a key with different row contents returns `409 idempotency_conflict`. Keys remain reserved for as long as the append-only row is retained. The lookup is a linear scan by the selected field (only `id` uses the B+Tree), so this API favors correctness for small account/result tables over large-scale key lookup. A fsync/index error still disables the table under the existing recovery contract.

One statement locks only its target table. That lock serializes ID allocation, append, fsync, B+Tree update, and SELECT file reads; SELECT uses a separate file handle. Different tables can proceed concurrently. `execute_many` is an internal durable batch primitive: all IDs are acknowledged only after the batch file is fsynced and indexed.
