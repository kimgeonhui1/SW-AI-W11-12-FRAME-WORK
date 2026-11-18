# Poker Lab audit and persistence contract

## P0 code audit

Before the Hold'em engine change, `Demo` owned one process-wide `game` dict and an `RLock`. Its lock serialized the single match, but game and user identity disappeared on process restart. `start` appended a `matches` row before dealing; actions only accepted `call` or a fixed `raise`, the bot called, and the match never reached showdown. The 52-card deck was shuffled with `SystemRandom`; however, no complete street or hand evaluator existed.

The old API accepted the action and raise target from the client, but had no action key, account identity, or profile boundary. The server did keep stacks and cards out of writable request fields. Its Redis value used `_public()` and therefore contained the human's hole cards; the current implementation now caches a separate public projection with no hole cards. The Mini Redis store is still just a cache. Mini DBMS uses append-only JSONL rows, fsync, an ID B+Tree, and linear equality scans for non-ID columns. It has no SQL UNIQUE, UPDATE, DELETE, or multi-row transaction.

The current `PokerEngine` owns deck, private cards, street contributions, turn queue, raise rights, board, chip accounting, hand evaluation, and settlement. Its UI is a caller of the HTTP API and cannot set cards, stacks, winner, or pot. `Demo` stores a separate engine and lock per authenticated guest. The bot's check/call policy runs in the server.

## Implemented data model

| Logical record | Mini DBMS representation | Reason |
|---|---|---|
| User | `guest_users`: `user_id`, `token_hash`, `display_name`, `created_at` | Additive table; old `players` rows and schema remain unchanged. `token_hash` is the lookup key. |
| Match | Existing `matches`: DBMS user row ID in `player_a`, reserved bot ID `-1` in `player_b` | One append-only match row; `match_key` is deterministic from user ID and client retry ID. |
| Completed Hand | Existing `hand_results`: operation key, payload hash, prior result ID, starting/ending stacks, winner, reason, board, rules version | One row contains both the settled result and public action history. |
| Hand actions | JSON in `hand_results.public_actions` | Keeping actions and result in one row avoids a cross-row transaction the DBMS does not provide. Private cards are never stored there. |
| Profile totals | Derived from `matches` and `hand_results` on `GET /api/profile` | No duplicate counters that can drift from individual records. Redis is not consulted. |
| Rank event | Not implemented | Competitive ranking is disabled until human-v-human matches exist. |

Every completed Hand row has key `{match_key}:hand:{hand_no}:result`. Its hash covers all immutable row fields except the DBMS ID and hash itself. `prev_result_id` forms a per-match append chain. Recovery verifies the key sequence, hash, chain, public-action field allowlist, and chip conservation. A mismatch returns a storage error; the server does not clear or reinitialize history.

## Append-once and uncertain outcomes

`POST /sql/insert-once` is a small additive DBMS API. The executor takes the target table's existing reentrant lock, scans for the selected key, compares the full row, and appends only if absent. The check, ID allocation, file append, fsync, and B+Tree/index update stay within the existing table synchronization. An exact retry returns the original ID. A reused key with different contents returns `409 idempotency_conflict`.

This closes the delay window for a Poker API retry: if the original INSERT is still running, either request can acquire the DBMS lock first; the other then observes the same key instead of appending a second result. Keys are reserved by permanent append-only rows, so compaction or deletion would need to preserve this contract. The lookup is linear by non-ID key and holds a table lock; it is correct for the small account/result tables here, but can limit throughput as those tables grow.

If a hand is settled in memory but the DBMS response is lost, the session keeps the exact immutable row and its operation key, returns `result_storage_unknown`, and blocks new actions/next Hand. A repeated `action_id` retries the same append-once row. The tests simulate the response being lost after the DBMS durably appended it: retry confirms the original ID and the table still has one result. If the DBMS is unavailable or its table is disabled after an uncertain fsync/index failure, the hand remains blocked until the exact row is confirmed or the DBMS recovers. There is no compensating chip reset.

Normal API responses distinguish an in-memory hand result (`handOver`) from durable confirmation (`recordStatus: confirmed`). Redis failures are traced but do not prevent a DBMS result append or profile recovery. Trace rows include a server-generated `traceId`, route, service, status, and outcome; request bodies, bearer tokens, token hashes, and private cards are excluded.

## Guest identity and restart behavior

The project is local and currently has one player against a bot, so it uses a stable browser guest token rather than passwords or a custom password/session system. The browser creates 32 random bytes with Web Crypto, stores the base64url bearer in `localStorage`, and sends it in the `Authorization` header. The server hashes it with SHA-256 and resolves the DBMS account row. `user_id` is derived from that hash and is never trusted from the request body. A name is selected at guest creation and is immutable because the DBMS has no UPDATE. The token is a bearer credential: loss of local storage means no account recovery, and this local HTTP setup is not suitable for an Internet-facing deployment.

Guest users, matches, and completed Hand results survive Poker API restarts. A new API process reconstructs completed stacks and hand number from `hand_results`; replayed hands continue with alternating heads-up button order. Redis can be completely empty and the profile remains correct. An in-progress Hand's deck and current betting state remain process memory only. A Poker API restart discards that unfinished virtual hand; it is not counted as a completed result. Because matches are append-only, such an interrupted match can remain in the match count without a completed Hand.

Mini DBMS must be restarted using the same data directory after adding `guest_users` and `/sql/insert-once`. Existing table files are only read/recovered; no migration rewrites them. A malformed DBMS row file retains the DBMS's existing fail-start behavior.

## Rank system — design only

Practice results and competitive rank remain separate. Bot outcomes never create rating events. Rank activation requires authenticated human-v-human matches, a stable match completion record, and a known policy for disconnects and forfeits.

| Candidate | Fit | Cost / limit |
|---|---|---|
| Pairwise Elo family | Easy to explain for heads-up wins/draws, low data needs, straightforward replay from an append-only event stream | A single rating can be overconfident for new players; a K policy and initial placement rule need evidence. |
| MMR with uncertainty (for example, a TrueSkill-like model) | Represents uncertainty and can extend to multiplayer teams or larger tables | More parameters and validation; ranking outcomes are harder to explain and compare with small pilot data. |

No formula, K value, tier boundary, season length, or placement count is selected here. First collect consented human match data and compare candidate ratings by held-out outcome prediction and stability; confirm target table size and match format before setting the model.

When enabled, a rating event should be appended only after a server-final match result, with a deterministic operation key, rules/model version, season, participant IDs, prior/new rating values, and links to the result record. Replay must be deterministic; duplicate submissions must resolve to the same event. Current Mini DBMS append-once can prevent duplicate keys, while event replay can rebuild a rating after restart. Disconnect policy, forfeits, and anti-abuse thresholds remain product decisions and must be fixed before ranked play. Any future rating write must remain separate from practice stats.

## Remaining boundaries

- There is no password login, token rotation, multi-device recovery, display-name editing, or completed-account deletion.
- An unfinished Hand is not restored after API restart; virtual chips have no monetary value.
- `guest_users.token_hash` and hand idempotency lookups scan table rows. A secondary key index is a future performance change, not a transaction guarantee.
- `hand_actions` and `player_results` are not separate DBMS tables; public actions are co-stored with the Hand result, and profile totals are derived.
- Rank, human-v-human play, side pots for more than two players, and augmented modes are outside this implementation.


## Phase 1 settlement integrity audit (2026-11-13)

The three mutating entry points (`start`, `next_hand`, `action`) now use one
`_finish_transition` path: run any bot actions, persist a completed hand, cache
public state, then return confirmed success or the existing storage error.
This includes hands completed by blinds without an action and by an automatic
bot call while starting/recovering a hand. Request replay entries are retained
even for UNKNOWN results, so the same request retries the immutable pending row
without dealing another hand or paying the pot again. `start` also checks pending
or conflicting storage before returning a replay or replacing a finished match.
A newly active hand has `recordStatus: not_saved`; the previous hand's confirmed
status is not inherited. No table schema, operation key, or append-once contract
was changed.

### Verified paths and failure cases

`tests/test_settlement.py` uses real localhost Poker/DBMS/Redis HTTP servers and
a separate TemporaryDirectory per test. Short-stack fixtures are obtained by
playing and saving a deterministic first hand from the normal 1000/1000 stacks;
production state or existing data files are not edited.

- Recovered `start` and `next_hand`: blind-only runout and bot-call completion.
- Human fold/check and bot call/check: settlement, including a tied board.
- Same start/next/action retry: one result key, unchanged stacks and hand number.
- Concurrent terminal action retries: one durable result row.
- Failed append and lost response after append: UNKNOWN, blocked transitions,
  then confirmation of the same row after service recovery.
- Conflict: blocked state cannot be bypassed by a start replay or a new match.
- Injected DBMS fsync exception: table remains unavailable until file recovery;
  the retained pending payload then reuses the recovered row.
- Result chains: prior result ID, unique operation keys, nonnegative final stacks,
  and total chips remain consistent. Temporary DB files can be reopened.

### Restart boundary: not crash-safe exactly-once execution

An API restart after a successful append but lost acknowledgement preserves the
completed record. Profile recovery sees it once; replaying the original start ID
loads that match's completed ledger. GET /api/game itself does not recover a game.
An API restart before any result append loses the in-memory pending payload and
completed-but-unsaved result. The regression test for this case characterizes
that existing limitation; a passing test does NOT establish durable recovery.
Start/next/action replay maps are also process-local, so command deduplication
across API restarts is not guaranteed. Retrying an old action after a recovered
hand is active must not be advertised as safe across restarts.

To close this boundary, a separate storage-contract change is required. A durable
pending-result outbox can recover failures after the outbox write, but alone
leaves the gap between an in-memory transition and that write. Stronger recovery
requires a durable accepted-command/state journal, stable command identities,
private deck/RNG recovery, and deterministic replay before serving a recovered
session. This affects the API, storage schema, recovery ordering, privacy, and
crash-injection tests; it is deliberately not implemented as a local fix.

The tests simulate API restart by replacing Demo and DBMS recovery by reopening
temporary files. They do not kill OS processes, simulate power loss, prove disk
hardware durability, or verify multiple API writers. Existing live service data
and processes are not used or restarted.

### Test environment

The WindowsApps python alias was inaccessible. Tests use the installed
Python 3.14 executable directly with `-B` to avoid changing bytecode caches.
Sandbox HTTP tests initially failed with WinError 10013; the DBMS saturation
assertion also failed because requests never reached its worker. With authorized
localhost access, the unchanged baseline Poker suite passed 25 tests and DBMS
passed 16 tests. Eleven of the first fourteen new regression cases failed before
the fix. Run the full Poker suite from projects/poker_demo with
`python -B -m unittest discover -s tests -v`, and the DBMS suite from projects/dbms
with the same command. All tests use temporary data rather than live databases.

Final validation: Poker 42/42 passed (25 existing + 17 new); unchanged DBMS
16/16 passed. The restart-before-append case documents a known limitation, not
a durability guarantee.
