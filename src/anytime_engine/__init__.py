"""anytime-engine — concern-based proactive orchestrator core.

Shared across agent repos. Domain content — concerns, providers, action
prompts — stays in each agent repo; this package holds only the deterministic
engine:

  registry      Concern dataclass, register/discover/validate/resolve
  reducer       reduce(trigger, state) -> action plan dict
  assembler     provider registry + context assembly
  topo_sort     Kahn's algorithm for dependency levels
  state         State (timers/flags/caches), corruption tolerance, backups
  heartbeat     single-instance lease
  prompts       @action prompt registry + shared formatting helpers
  calendar_reconcile      pure calendar set-diff (drift detection)
  calendar_reconcile_cli  CLI wrapper writing the scan-cache
  config        per-repo paths + review schedule

Canonical source: thufir-assistant `packages/anytime-engine/`. Consumer repos
vendor a copy via `sync-to.sh` — never edit the vendored copy directly.
"""

__version__ = "0.2.2"
