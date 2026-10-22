"""anytime_cases — the cases concern pack for anytime-engine.

Optional, like anytime_calendar: not part of the core and not vendored by
default. `sync-to.sh <agent-repo> --pack cases` copies it next to
`anytime_engine/` and lists it in mentat.json `components.engine.plugins`
(no mentat.json: ANYTIME_PLUGINS=anytime_cases):

    providers  cases.due, cases.signals          (due.py)
    concerns   cases_morning, cases_deadline     (concerns.py)
    backends   markdown frontmatter | admin API  (source.py, admin.py)
    executor   python3 -m anytime_cases.deliver  (deliver.py, render.py, telegram.py):
               renders the messages, sends them on the chosen channel (file |
               telegram), marks delivered: only after a confirmed send

Rules: docs/concern-packs.md (the pack contract) and docs/cases-pack.md.
"""

ANYTIME_PLUGIN = {"name": "cases", "engine": ">=0.3,<0.4"}
