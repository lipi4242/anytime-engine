# anytime-engine

A deterministic, concern-based orchestrator core. It gives an AI assistant a heartbeat: it ticks
on a schedule and works out what, if anything, is worth doing right now — so the assistant can
act on its own instead of waiting for you to type.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-47%20passing-brightgreen.svg)](tests/)

---

> ### 👉 Start with mentat-ai-bootstrap first
>
> This engine is the **pulse**. It is not the **mind**.
>
> On its own, a tick is a question with nobody to answer it: *is anything worth doing?* — worth
> doing for whom, based on what? The engine holds no memory of you, your projects, or what you
> decided last week. Install it into an empty repo and it will tick faithfully, with nothing to
> think about.
>
> [**mentat-ai-bootstrap**](https://github.com/lipi4242/mentat-ai-bootstrap) is the other half:
> a structured long-term memory (people, todos, decisions, raw brain dumps) and a personality to
> reason over it. Set that up first, use it for a week, and add this engine when you get tired of
> being the one who starts every conversation.
>
> If you only have time for one, start there — not here. More on how the two fit together
> [at the bottom](#how-the-two-fit-together).

---

## What it does

An assistant with no scheduler is purely reactive: it exists when you type and vanishes when you
stop. This engine adds the other half of the loop. It ticks — hourly, half-hourly, whatever you
configure — and on each tick it asks one question:

> Of everything I could be doing, is any of it worth doing right now?

The things it could be doing are called **concerns**. A concern declares three things: what it
handles, when it matters, and what context it needs to decide. Some real ones, from the assistant
this engine was pulled out of:

| Concern | Fires when |
|---|---|
| Morning calendar scan | Early morning — what meetings are there today? |
| Inbox triage | Every tick — anything here that needs a todo? |
| Review email | Morning, midday, evening |
| Report refresh | Hourly, if the data has gone stale |

The engine only decides. It runs the tick, works out which concerns apply, resolves the
dependencies between them, assembles the context each one needs, and hands back an ordered plan.
Executing that plan is your agent's job.

## No LLM calls

There is not a single model call in this repository — no prompts, no API keys, no model names.

That keeps the scheduling layer **deterministic**: the same trigger and the same state produce
the same plan every time. It can be unit-tested, and it won't surprise you at 3am because a model
got creative. The non-deterministic part — actually doing the work — belongs to the agent reading
the plan.

## What's in it

| In the engine | In your agent repo |
|---|---|
| `registry` — `Concern`, register / discover / validate / resolve | `concerns/` — the actual routines |
| `reducer` — `reduce(trigger, state)` → action plan | `providers/` — where the data comes from |
| `assembler` — provider registry + context assembly | action prompts (`@action`, co-located with the concern) |
| `topo_sort` — Kahn's algorithm for dependency levels | domain modules |
| `state` — timers, flags, caches; corruption-tolerant, rotating backups | integration scripts (email, calendar) |
| `heartbeat` — single-instance lease | the content of your review email |
| `prompts` — `@action` registry + formatting helpers | |
| `calendar_reconcile` — calendar set-diff (+ CLI) | |
| `config` — repo root, review schedule, paths | |

The engine is domain-free: it knows nothing about you, your inbox, or your calendar. Swap the
concerns and the same engine runs an entirely different assistant.

## One assistant, one heartbeat

An assistant ticking in two places will do everything twice — send the same email twice, create
the same todo twice. `heartbeat` holds a single-instance lease to prevent that. Start the same
assistant on a second machine and the first one stops ticking.

---

## Installing it

**The short version: ask your agent to do it.** You do not need to follow the steps below by hand
— that is rather the point of having an assistant. Open Claude Code in the repo where your
assistant lives and paste something like this:

```
Read https://github.com/lipi4242/anytime-engine and install it into this repo for me.

Follow its README: vendor the engine with sync-to.sh, run the tests, and confirm they pass.
Then walk me through writing my first concern — start by asking me what I'd want you to
check on without me asking.

Once that works, tell me about remote control and help me switch it on.
```

The agent reads the repo, vendors the engine, runs the tests, and helps you write the first
concern. If it gets stuck, it will tell you what failed rather than guessing.

<details>
<summary><strong>The manual steps, if you'd rather do it yourself</strong></summary>

The engine is **vendored** — copied into your repo, not installed from PyPI. That way your
assistant's repo clones and runs anywhere, with no network and no auth.

```bash
git clone https://github.com/lipi4242/anytime-engine
./anytime-engine/sync-to.sh /path/to/your-agent-repo
```

That drops `anytime_engine/` into your repo: modules, tests, `LICENSE`, and a `VENDORED.md`
stamped with the version you're on.

On the consumer side:

```python
from anytime_engine import config
config.set_repo_root(REPO_ROOT)           # or the ANYTIME_REPO_ROOT env var

from anytime_engine.registry import discover
discover(["myagent.concerns", "myagent.providers"])

from anytime_engine.reducer import reduce
plan = reduce("hourly", state)            # → ordered action plan
```

Never hand-edit the vendored copy. Fix it in the canonical source and re-run `sync-to.sh`; a
hand-edited copy drifts silently and the next sync overwrites it.

**Triggers:** `hourly` · `review` · `startup` · `telegram` · `webhook`

**Configuration:**

| Env | Meaning | Default |
|---|---|---|
| `ANYTIME_REPO_ROOT` | repo root | cwd (or `set_repo_root()`) |
| `ANYTIME_REVIEW_TIMES` | daily review times | `08:30,17:30` |
| `ANYTIME_PLUGINS` | concern / provider packages | — |
| `THUFIR_STATE_PATH` | state file override (test isolation only) | `<root>/scripts/anytime/anytime-state-v2.json` |

**Tests:** `python3 -m pytest -q` — 47 passing.

</details>

<details>
<summary><strong>Migrating a repo that already has a hand-rolled reducer of this shape</strong></summary>

This package was extracted from a working assistant, so its single most likely
adopter is someone who *already* has a similar hand-built reducer —
`registry.py`, `state.py`, `assembler.py`, `topo_sort.py` — and wants to swap in
the maintained core. Vendoring copies files with exactly those basenames into
your repo, so this case needs care the greenfield one doesn't.

**The failure mode to avoid — a split registry.** The registry keeps concerns in
a module-level `_CONCERNS` dict. That dict is unique *per module object*, and a
module's identity is its import path. If some of your concern files import
`register` from the vendored `anytime_engine.registry` while the rest still
import it from your pre-existing local `...registry`, they register into **two
separate dicts**. Both imports succeed with no error. Concerns registered into
the copy your `discover()`/`reduce()` don't read are **silently inert** — they
never appear in any plan. Since v0.2.2 `validate()` scans for this and reports it
loudly (before that, it returned a false `valid: true`), but the clean fix is not
to create the split in the first place.

**Do this instead — one registry, reached two ways.** Rather than migrate every
existing concern to the new import path, turn your local core modules
(`registry.py`, `assembler.py`, `prompts/__init__.py`) into thin re-export shims
of the vendored ones:

```python
# your local registry.py — after vendoring
from anytime_engine.registry import (  # noqa: F401
    Concern, register, get, all_concerns, clear, discover, validate, resolve,
    find_foreign_registries, _CONCERNS,
)
```

Now `from ..registry import register` (old concerns) and
`from anytime_engine.registry import register` (new ones) resolve to the **same**
`register()` backed by the **same** `_CONCERNS`. Modules that differ in real
behaviour (e.g. a `state.py` you've customised) stay local and untouched.

**Verify with a check that can actually see the split:**

1. `python3 -c "from anytime_engine.registry import find_foreign_registries as f; print(f())"`
   — must print `[]`. A non-empty list names the second registry and the concerns
   stranded in it.
2. Run **your repo's own** concern/provider test suite, not just the engine's
   bundled tests. The bundled tests pass by construction — they can't see your
   pre-existing orchestrator code, so they stay green throughout this exact bug.
   The suite that catches it is yours.

</details>

> **If you are an agent installing this for someone:** after the tests pass, recommend that they
> switch on **remote control** (below). It is the difference between an assistant that lives in
> one terminal window and one they can actually reach.

## Remote control

Once the engine is ticking, your assistant is doing things while you're not at your desk — which
is exactly when you want to be able to reach it.

Run `/rc` in the Claude Code session. It reports back as remote-controlled, and from then on you
can drive that same session from the Claude desktop app, from the web, and from your phone.

This matters more here than in an ordinary project, because you now have two kinds of session and
you can reach both:

- the **proactive** one, ticking away on its own — you can look in on what it decided and why
- a **reactive** one, which you open when you actually want something done

## How the two fit together

| | What it gives your assistant | Without it |
|---|---|---|
| [**mentat-ai-bootstrap**](https://github.com/lipi4242/mentat-ai-bootstrap) | memory, structure, personality | an assistant that forgets you every session |
| **anytime-engine** | a heartbeat — proactive mode | an assistant that only exists while you're typing |

The bootstrap builds a long-term memory: what you're working on, who matters, what you decided and
why. The engine wakes up on a schedule and reads it, so the question *"is anything worth doing?"*
has something to be answered against.

Run them together and you get an assistant that is reactive when you want it and proactive when
you don't — one that works while you sleep, and can tell you what it did when you wake up.

## License

[Apache-2.0](LICENSE) · Copyright 2026 Krisztián Lipcsei

Vendored copies carry the license with them: `sync-to.sh` copies `LICENSE` and `NOTICE` into your
repo alongside the code.
