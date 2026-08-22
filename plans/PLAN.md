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
| Phase 2 | **Deferred (not complete)** — 2.1–2.6, 2.9 (mostly) done. Open and postponed: §2.7 (admin rework), §2.8's SMS provider (OTP login code-path exists but not production-usable), §2.9's `/oauth/dev/start` scopes. Active phase moved to Phase 3 on 2026-08-22 — see PLAN.md. |
| `PHASE3.md` | **Current active phase** — read the specific `## 3.X` section for your task |
| `PHASE4.md`, `PHASE5.md` | Not started — do not read unless explicitly told to |
| `CHECKLISTS.md` | Security Checklist, Pre-Production Checklist, Future Improvements |
| `CHANGELOG.md` | A past decision seems relevant/contradictory to what you're building — spot-check, don't read cover-to-cover by default |
| `STATUS.md` | Quick current-status table |

**Do not assume you can skip `CHANGELOG.md` entirely** — if `PHASE2.md` or `REFERENCE.md`
references a dated decision you need to verify, go read that specific entry. The point of
the split is to avoid reading the *entire* history for every task, not to hide it.

---

## Active Phase

> Set this manually before each coding session.
> **Current: Phase 3** (Seller Web Platform)
>
> **Phase 2 deferred, not fully complete.** Remaining Phase 2 items are explicitly
> postponed, not abandoned — see `PHASE2.md`'s own status note at the top of the
> file for what's open (§2.7 admin rework, §2.8 SMS provider, §2.9's one open
> item). Do not silently pick these up while working on Phase 3; if a Phase 3
> task turns out to depend on one of them, stop and flag it rather than
> resolving it inline.
>
> **For this phase, read `PHASE3.md`.**

---

See `STATUS.md` for the full phase-by-phase status table.