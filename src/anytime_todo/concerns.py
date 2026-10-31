"""Concern `todo_esedekes`: the agent's due recurring duties, one generic concern.

Planned by an hourly or review tick while the todo API lists an occurrence
that is due (date and, if set, time in the task's tz) and owed (occurrence.py),
or while a long API outage has not been reported today. Off when not configured.
"""
from __future__ import annotations

from typing import Any

from anytime_engine.prompts import action, format_context
from anytime_engine.registry import Concern, register

from . import due

register(Concern(
    name="todo_esedekes",
    description="Due recurring duties (repeating todos in the Mentat Admin): do them, then complete them.",
    triggers=["hourly", "review"], should_run=due.owed, context_needs=["todo.due"],
    action="todo_esedekes", staleness_minutes=60))

CLI = "python3 -m anytime_todo.cli"

_RULES = f"""Each item is one occurrence of a recurring duty. Its `title` and
`description` ARE the instruction: do what they say, within your existing
rules and approvals (a todo is not an approval; if the action needs one, it
still needs it).

`due` — for each item, in order:
  1. `{CLI} start <id> --due <due_date>` BEFORE you begin.
  2. Do the work.
  3. ONLY after it really happened: `{CLI} done <id> --due <due_date> --rev <rev>`.
     Exit 0 = completed (a repeating task moves to its next date on the server).
     Exit 3 = the work is recorded but the completion did not land: it is retried
     on the next tick as `complete_pending`; do not redo the work.
  4. Cannot do it now (missing input, needs approval, a tool is down):
     `{CLI} note <id> --due <due_date> --text "<why, in one sentence>"`. It stays
     open with that comment and comes back in {{retry}} h. Never skip silently,
     never complete what did not happen.

`complete_pending` — the work was ALREADY DONE: only run the `done` command again.

`interrupted` — a run was started earlier but neither finished nor noted (a
crash?). First check whether it happened (message sent, file written, ...).
Happened -> `done`. Clearly not, and safe to do -> do it, then `done`.
Unsure, or it has an outbound effect that could double -> `note`, do not repeat.

`invalid` — tasks this engine cannot read: mention them to the owner once."""


@action("todo_esedekes")
def todo_esedekes_prompt(ctx: dict[str, Any]) -> str:
    data = ctx.get("todo.due") or ctx
    if isinstance(data, dict) and data.get("status") == "error":
        mark = (data.get("outage") or {}).get("mark")
        return ("# Recurring duties — the todo API is DOWN\n\n"
                f"Since {data.get('since')} the todo list cannot be read: {data.get('error')}\n"
                "Your recurring duties are not being scheduled while this lasts. Tell the "
                "owner once, in one short message (do not guess the duties from memory). "
                f"After the message is CONFIRMED sent: `python3 -m anytime_engine.tick --mark {mark}`.")
    if isinstance(data, dict) and "error" in data:   # the provider itself failed
        return f"# Recurring duties\n\nThe todo provider failed: {data['error']}. Do nothing else."
    return ("# Recurring duties (todo)\n\n" + _RULES.format(retry=f"{due.retry_hours():g}") + "\n\n"
            + format_context(data))
