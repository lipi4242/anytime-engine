"""anytime_bekotes — the bekötés (business wiring) concern pack for anytime-engine.

Optional, like anytime_cases: not part of the core. It keeps a business map
(written by the brain, `<brain root>/business/<name>/`) current by computing,
in plain Python, what changed in the business's sources since the last ingest:

    config   businesses(root): every business/*/bekotes.json under the brain
    cursor   <business dir>/kurzor.json, saved atomically (tmp + os.replace)
    sources  snapshot(src, root): repo HEAD, memory hashes, linear export, live sha
    diff     compute(biz, root, now, weekly): changes + deleted refs since the
             cursor, plus the full reconciliation of every "(forrás: …)"
             citation when its stamp says so (weekly.py);
             side-effect free — the cursor advances only after a success
    stale    mark(): " [elavult <day>]" on map lines citing a deleted ref
    pending  <business dir>/.pending-kurzor.json, the run under way
    concerns bekotes_frissites (daily, only on an actionable diff) + provider
    frissit  the CLI: --baseline / --begin / --advance <run_id> / --status

Rules: docs/concern-packs.md (the pack contract), docs/bekotes-pack.md.
"""

ANYTIME_PLUGIN = {"name": "bekotes", "engine": ">=0.3,<0.4"}
