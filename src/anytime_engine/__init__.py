"""anytime-engine — concern-based proactive orchestrator core.

Shared across agent repos. Domain content — concerns, providers, action
prompts — stays in each agent repo; this package holds only the deterministic
engine:

  registry      Concern dataclass, register/discover/validate/resolve
  plugins       concern-pack contract: ANYTIME_PLUGIN, in-repo only, collisions
  reducer       reduce(trigger, state) -> action plan dict
  assembler     provider registry + context assembly
  topo_sort     Kahn's algorithm for dependency levels
  state         State (timers/flags/caches); fail-closed load (state_load),
                file mechanics (state_files), review windows (state_reviews)
  receipts      durable record of finished concerns, overlaid on every load
  recover       operator CLI for a fail-closed state (status/restore/reset)
  heartbeat     single-instance lease
  prompts       @action prompt registry + shared formatting helpers
  config        per-repo paths + review schedule
  clock         the agent's local time (components.engine.timezone / ANYTIME_TZ)
  tick          the tick entry point a scheduler calls; writes the fleet
                stamps (heartbeat + last-tick.json) only after the work
  schedule      durable schedule recipe (systemd user timer / cron line)
  setup         after sync-to.sh, one command: timezone, delivery, selftest, timer
  selftest      the engine's own tests, stdlib, one exit code
  engine_manifest  the engine's keys in mentat.json (+ status CLI);
                mentat_manifest = vendored stopgap of the canonical LG1 reader
  verify        vendored copy = stamped VERSION, unmodified, the only copy
  versions      MAJOR.MINOR[.PATCH] + `>=,<` ranges (one grammar for all)

Optional packs live beside the core, not in it (`anytime_calendar`,
the `anytime_cases` concern pack).
Consumer repos vendor a copy via `sync-to.sh` — never edit the vendored copy
directly.
"""

__version__ = "0.3.0"
