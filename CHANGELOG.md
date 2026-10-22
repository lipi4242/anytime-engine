# Changelog

## 0.3.0 — 2026-10-22

**Breaking.** Pre-1.0, so the break goes in the minor version: the default state path, the
review-time default and the location of the calendar modules all changed, and an un-migrated
consumer would silently change behaviour (no review ever due, or a fresh state file). Migration
steps below.

### Added
- **`anytime_engine.tick`** — the entry point a scheduler calls:
  `python3 -m anytime_engine.tick <trigger> [--exec CMD] [--dry-run]`. It validates, reduces,
  hands the plan to your executor command, and writes the supervision stamps
  (`data/state/orchestrator-heartbeat.json`, and `data/state/last-tick.json` for `hourly`/`review`)
  **only after the work succeeded**. A failed or crashed tick stamps nothing. `--mark CONCERN`
  records completion from the executor; `--dry-run` decides and prints but writes nothing.
- **`anytime_engine.schedule`** — a durable schedule: a systemd user timer (`Persistent=true`) or,
  with `--cron`, a flock-guarded crontab line. Prints what it would install by default;
  `--install` writes and enables it.
- `sync-to.sh --pack calendar` vendors the optional calendar pack.
- `sync-to.sh --pack cases` vendors the cases concern pack (`anytime_cases`) and lists it in
  mentat.json `components.engine.plugins`; a pack already listed there comes along on every sync.
  The cases pack's tests skip where the pack is not vendored (they used to fail: 20 of 130).
- **Operation receipts** (`data/state/anytime-receipts.jsonl`): `mark_run`, `tick --mark` and
  `mark_review_serviced` append an fsynced receipt; every load overlays it, so losing or restoring
  the state never repeats a finished concern. `python3 -m anytime_engine.recover
  status | restore N | reset --yes`.
- **Injected clock**: `reduce(trigger, state, now=...)` pins one instant for the whole reduction;
  `state.now()` reads it. `tick --dry-run --now ISO` reproduces a plan.
- **`python3 -m anytime_engine.verify`**: the vendored copy matches its machine `VERSION`
  (version + content hash) and is the only engine copy in the repo. `sync-to.sh` writes `VERSION`
  and refuses a downgrade without `--allow-downgrade`.
- **Concern-pack contract**: `ANYTIME_PLUGIN = {"name", "engine": ">=X,<Y"}` in the package
  `__init__`; packs outside the repo, outside the declared engine range, or colliding on pack /
  concern / provider name are refused.
- **mentat.json**: the engine owns `components.engine` and `installed.engine`; plugins fall back to
  `components.engine.plugins`; `schedule --install` refuses when `schedule_owner` is `fleet`;
  `python3 -m anytime_engine.status`.
- **One-command install**: `python3 -m anytime_engine.selftest` is the single post-sync test
  command (0 = green); `python3 -m anytime_engine.setup` sets time zone and delivery and, with
  `--install`, the schedule. The engine works in the agent's local time zone, and `--now` also
  works on a live tick.
- **Cases pack**: delivers due cases (Telegram or file), with quiet hours for Telegram (no
  night-time pings; held messages go out when the window ends); todos with a due date reach the
  morning summary; `python3 -m anytime_cases.new` creates a case; `last` prints what the latest
  tick saw and did.
- **Telegram delivery goes through the sub-etha bridge**: `telegram.send` calls the bridge's
  `send.mjs` (text on stdin, token in env, chunking by the bridge). No own Bot API client and no
  `getUpdates`, so it never competes with the bridge's poller.
- **`anytime_bekotes` pack** (`sync-to.sh --pack bekotes`): keeps an onboarded agent's knowledge
  current — an ingest cursor, a daily diff of the business repos / Linear export / memories, and
  `stale` marks on claims whose source was removed. An empty diff costs no LLM call.
- **`sync-to.sh --only-pack NAME`** vendors one pack without touching the engine.
- **Engine block in the agent's `AGENTS.md`** — `python3 -m anytime_engine.setup --install`
  writes (and on re-run replaces) a short block: how to get a given day's morning summary
  (`preview --at`), where the summary really goes (file or Telegram), which time zone to speak in.

### Changed
- Default state file: `<root>/data/state/anytime-state.json` (was
  `<root>/scripts/anytime/anytime-state-v2.json`). The first load copies the old file forward and
  leaves it in place for a rollback; an explicit path override never migrates.
- `ANYTIME_STATE_PATH` replaces `THUFIR_STATE_PATH`. The old name is still honoured in 0.3.x, with
  a warning on stderr.
- No default review times (was `08:30,17:30`). With none configured, no review is ever due, and
  `review_due()` says so once on stderr.
- `calendar_reconcile` / `calendar_reconcile_cli` left the core and became the optional
  `anytime_calendar` pack (`anytime_calendar.reconcile`, `python3 -m anytime_calendar.cli`, which
  now requires `--state`). `sync-to.sh` removes the retired files from a vendored copy.
- The tests run under stdlib `unittest` — no pytest needed. After a sync, run
  `python3 -m anytime_engine.selftest` (the vendored tests, one command, one verdict).
- `State` resolves its path lazily, so `config.set_repo_root()` works even after import.

- **A corrupt or unknown-schema state no longer starts empty.** A newer schema fails closed (no
  tick, file untouched); a corrupt file is restored from a recent `prev.N`
  (`ANYTIME_STATE_RESTORE_MAX_GAP_MIN`, default 180), else fails closed; an older schema is
  migrated through an explicit chain after a `pre-migrate` backup.
- The reducer no longer special-cases a concern named `review_email`; list `review_type` in its
  `context_needs` (an engine built-in provider).

### Fixed
- Under plain `unittest`, the vendored smoke test wrote to the consumer's **live** state file:
  the isolation lived only in pytest's `conftest.py`. Every test that touches state now isolates
  itself (`tests/_engine_isolation.py`) under both runners.
- `registry.validate()` raised `ValueError` on a dependency on an unknown concern, instead of
  reporting it.
- `sync-to.sh .` (relative target) works, and a failed sync rolls the repo back to its pre-sync
  state (engine, packs, `mentat.json`, `.mentat/local.json`) — no half-installed engine.
- `sync-to.sh` no longer overwrites a newer vendored engine with older files at the same version.
- "Today" / "tomorrow", the last-tick stamp and the calendar CLI follow the agent's time zone; in
  Budapest they were a day off between 00:00 and 02:00 (UTC).
- Cases, markdown backend: a moved first occurrence keeps its own date, so a monthly series with an
  exceptional first month no longer falls apart.

### Deprecated
- `THUFIR_STATE_PATH` and `config.review_state_path()` — removed in 0.4.

### Migrating from 0.2.x
1. Re-sync: `./anytime-engine/sync-to.sh <your-repo>` (add `--pack calendar` if you used
   `calendar_reconcile`; then import `anytime_calendar.reconcile` and pass `--state` to the CLI).
2. If you relied on the default review times, set `ANYTIME_REVIEW_TIMES=08:30,17:30` — in the
   scheduler's environment as well as your shell.
3. Rename `THUFIR_STATE_PATH` to `ANYTIME_STATE_PATH` wherever you set it.
4. Add `data/state/` to `.gitignore`. Once you're sure you won't roll back, delete the old
   `scripts/anytime/anytime-state-v2.json` (and its `.prev.*` backups).
5. If your own entry point writes the heartbeat or `last-tick.json`, especially at the start of
   the tick, delete that code and call `anytime_engine.tick` from your scheduler instead.
6. Replace a session cron (`/loop`, CronCreate) with `python3 -m anytime_engine.schedule` (check
   the printed units, then `--install`). Keep the session cron only as a supplement.
7. A concern named `review_email` that used `context["review_type"]`: add `"review_type"` to its
   `context_needs`.
8. Declare each concern package: `ANYTIME_PLUGIN = {"name": "...", "engine": ">=0.3,<0.4"}` in its
   `__init__.py` (undeclared packages still load, with a warning).
9. Run `python3 -m anytime_engine.verify`; a second `registry.py` + `reducer.py` in the repo must go.
10. Run the tests: `python3 -m unittest discover -s anytime_engine/tests`, and your own suite.
