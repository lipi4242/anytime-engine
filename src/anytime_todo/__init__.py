"""anytime_todo — recurring duties as repeating todos (the todo concern pack).

A fixed-cadence duty of an agent (weekly reminder, morning round, monthly
check) is a repeating task in the Mentat Admin todo plugin, not a cron job and
not a concern of its own. The todo IS the schedule: completing a repeating
task rolls its due_date forward on the server. This pack is the one generic
concern that reads them:

    concern    todo_esedekes (hourly, review)          concerns.py
    provider   todo.due                                due.py
    settings   TODO_API / TODO_HANDLE / TODO_TOKEN_FILE settings.py
    client     the todo API (/api/todo/v1)             api.py
    receipts   per-occurrence started/worked/completed/held   marks.py
    executor   python3 -m anytime_todo.cli start|done|note|list

Off (no plan entry, no noise) until TODO_API + TODO_HANDLE are configured.
Rules: docs/todo-pack.md (dev repo) and the pack contract (concern-packs.md).
"""

ANYTIME_PLUGIN = {"name": "todo", "engine": ">=0.4,<0.5"}
