"""anytime_calendar — optional calendar pack for anytime-engine.

Not part of the engine core (moved out in 0.3.0: the core is domain-free).
A pure, tested calendar set-diff that notices deletions and moves, not only
additions, plus a CLI that reconciles a JSON scan-cache against a fresh scan.

    from anytime_calendar.reconcile import reconcile, changes_since
    python3 -m anytime_calendar.cli --state <cache.json> --fresh <scan.json> \\
        --window-start <iso> --window-end <iso>

Vendor it by copying this directory next to anytime_engine/ in your repo.
"""
