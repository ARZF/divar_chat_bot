# Divar Chatbot — Development Plan (Index)

> **FOR AI AGENTS — READ BEFORE ANY CODE GENERATION**
>
> - This file is the **entry point only**. It tells you which other file(s) to read for
>   your actual task — it does not contain full task specs itself.
> - Work **only** on tasks explicitly listed as `[ ]` in the **current active phase**.
> - Do **not** scaffold, stub, or touch files belonging to future phases.
> - Do **not** commit or echo `.env`, secrets, API keys, or password hashes anywhere in source files.
> - Do **not** invent schema fields, endpoints, or logic not listed in the relevant phase file.
> - When a task is ambiguous, **stop and ask** rather than assume.
> - All functions must match the signatures defined in the relevant phase file exactly.
> - Test files go in `tests/` and mirror the `app/` structure. Do not mix them.

---

## How to use this plan (read this first)

This plan is split across files in `plans/`. **Only read what your task needs:**

| File | Read when... |
|---|---|
| `PLAN.md` (this file) | Always — tells you active phase + which file(s) to open next |
| `REFERENCE.md` | You need existing-file notes, tech stack, or the project structure tree |
| `PHASE1.md` | Your task references Phase 1 code/bugfixes, or you're touching Phase 1 files |
| `PHASE2.md` | **Current active phase** — read the specific `## 2.X` section for your task |
| `PHASE3.md`, `PHASE4.md` | Not started — do not read unless explicitly told to |
| `CHECKLISTS.md` | Security Checklist, Pre-Production Checklist, Future Improvements |
| `CHANGELOG.md` | A past decision seems relevant/contradictory to what you're building — spot-check, don't read cover-to-cover by default |
| `STATUS.md` | Quick current-status table |

**Do not assume you can skip `CHANGELOG.md` entirely** — if `PHASE2.md` or `REFERENCE.md`
references a dated decision you need to verify, go read that specific entry. The point of
the split is to avoid reading the *entire* history for every task, not to hide it.

---

## Active Phase

> Set this manually before each coding session.
> **Current: Phase 2** (Phase 1 complete including all bugfixes 1.B1, 1.B2, 1.B3.
> Build order: ~~2.2~~ → 2.8 partial (OTP/SMS deferred; see `CHECKLISTS.md`) → ~~2.7~~ → ~~2.3~~ → (~~2.1~~ ∥ ~~2.4~~ ∥ ~~2.6~~) → ~~2.5~~ → 2.9 partial → 2.7 admin rework)
>
> **For this phase, read `PHASE2.md`** — the `## 2.7` admin rework is next per build order.
> §2.9 was built out on 2026-08-16 and is **substantially implemented but not complete**: the
> `/oauth/dev/start` scopes remain open. The `refresh_access_token()` per-seller defect found
> while auditing those commits is fixed, together with event re-registration on refresh; the
> row lock added there is **unverified against PostgreSQL** (SQLite drops `FOR UPDATE`) — read
> §2.9's resolved-defect note before touching that path.
> `PHASE2.md`'s own intro references `REFERENCE.md` and `PHASE1.md` where
> relevant — follow those pointers as needed, don't read them preemptively in full.

---

See `STATUS.md` for the full phase-by-phase status table.
