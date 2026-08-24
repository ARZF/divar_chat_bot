# Project Rules

## Plan Navigation

This project's development plan is split across files in `plans/`, not a single file.

- Always read `plans/PLAN.md` first. It tells you the active phase and which other
  file(s) to open for your specific task.
- Do NOT read every file in `plans/` by default — follow `PLAN.md`'s routing table
  and only open the files it points you to for your current task.
- If a file you're reading (e.g. `plans/PHASE2.md`) references `plans/CHANGELOG.md`
  or `plans/PHASE1.md` for a specific dated decision or prior fix, open that file to
  verify the specific claim — don't skip it, and don't read it cover-to-cover either.
- Never invent schema fields, endpoints, or logic not explicitly listed in the relevant
  phase file. When something is ambiguous or underspecified, stop and ask rather than
  assume — do not fill gaps yourself.

## Use Codebase Memory MCP for Code Discovery & Reading

### Rule

When you need to search, locate, read, or trace code in the codebase, **prioritize Codebase Memory MCP tools** over `grep`, `glob`, or manual file-by-file reading.

### Why

The Codebase Memory MCP provides a knowledge graph of the codebase — functions, classes, routes, call/data-flow edges, and semantic search. This is faster and more context-aware than flat text search. `grep`/`glob` only match text; the MCP understands structure, relationships, and meaning.

### Prerequisite: Index First

If the project is not yet indexed, call `index_repository` with `repo_path` and `mode` (recommended: `full` for best semantic/similarity edges, or `fast` for a quick pass). Use `index_status` to check if indexing is needed, and `detect_changes` to re-index after code changes.

### Tool Selection Guide

| Task | Use This MCP Tool | Instead Of |
|------|-------------------|------------|
| Find functions/classes/routes/variables by keyword or natural language | `search_graph` with `query` param (BM25 ranked) | `grep` |
| Find symbols by regex name pattern | `search_graph` with `name_pattern` param | `grep` / `glob` |
| Semantic/conceptual search (find "publish" when searching "send") | `search_graph` with `semantic_query` (array of keywords) | `grep` |
| Read source code of a specific function/class | `get_code_snippet` with `qualified_name` | reading entire files |
| Find callers, callees, or data-flow paths | `trace_path` with `mode` param (`calls`, `data_flow`, `cross_service`) | manual `grep` chaining |
| Complex multi-hop queries, aggregations, hot-path analysis | `query_graph` with Cypher | manual multi-step `grep` |
| Understand project architecture & modules | `get_architecture` | guessing from folder structure |
| Text pattern search enriched with graph context | `search_code` (grep + structural ranking) | bare `grep` |
| Check graph schema (node labels, edge types) | `get_graph_schema` | — |

### How to Apply

1. **First check indexing:** Call `index_status` for the project. If not indexed, run `index_repository`. After code changes, call `detect_changes` and re-index if needed.
2. **First choice:** Use the appropriate MCP tool from the table above.
3. **Fallback:** If the Codebase Memory MCP is unavailable, not connected, or returns no results, fall back to `grep` / `glob` / standard `read_file`.
4. **Do not** default to running `grep` or `rg` via shell commands when the MCP can accomplish the same task.

### Important Notes

- `search_graph` results are capped at `limit` (default 200). Check the `has_more` field and paginate with `offset` if needed.
- `get_code_snippet` is a **read** tool, not a search tool. Call `search_graph` first to find the exact `qualified_name`, then pass it to `get_code_snippet`.
- `search_graph` `semantic_query` must be an **array** of keyword strings (e.g. `["send","pubsub","publish"]`), not a single string.
- `search_graph` `query` and `name_pattern` are independent — when `query` is provided, `name_pattern` is ignored.
- `search_code` has no `offset` parameter — to see more results, raise `limit` or narrow with `file_pattern` / `path_filter`.

### Scope

- Applies to all code-search, code-reading, symbol-discovery, call-tracing, and architecture-understanding tasks.
- Does **not** apply to executing build/test/lint commands or modifying files — those should use the standard tools.

## Git Commit Messages

- **All Git commit messages MUST follow the Conventional Commits specification.**
- Every commit message MUST use this format:

  `<type>(<scope>): <description>`

- Allowed commit types:
  - `feat` — a new feature
  - `fix` — a bug fix
  - `refactor` — code restructuring without changing behavior
  - `test` — adding or modifying tests
  - `docs` — documentation-only changes
  - `chore` — maintenance tasks that do not affect application behavior
  - `build` — dependency or build-system changes
  - `ci` — CI/CD changes
  - `perf` — performance improvements
  - `style` — formatting/style-only changes

- Use a **meaningful and specific scope** whenever applicable, based on the affected module or domain.

- Examples of valid scopes:
  - `auth`
  - `oauth`
  - `chatbot`
  - `webhook`
  - `divar`
  - `db`
  - `plans`
  - `git`

- The commit description MUST:
  - Be concise and specific.
  - Use imperative/command-style wording.
  - Start with a lowercase letter.
  - NOT end with a period.

- **NEVER create commits with a plain sentence without a Conventional Commit type.**

- Invalid examples:
  - `Fix refresh token handling`
  - `Add event subscription`
  - `Wire supplier message handler`
  - `Document ConversationState move`

- Valid examples:
  - `fix(oauth): return real expires_in from refresh_access_token`
  - `feat(webhook): add event subscription handling`
  - `feat(chatbot): add supplier message handling`
  - `docs(plans): document ConversationState move`

- **NEVER omit the commit type**, even for small changes.

- If a change belongs to multiple independent concerns, **prefer separate commits** rather than combining unrelated changes into one commit.

- Do NOT use broad or meaningless scopes such as:
  - `misc`
  - `stuff`
  - `changes`
  - `general`

- Before creating a commit, inspect the staged changes and determine the correct `type` and `scope` from the actual changes.

- **Do not guess the commit type from the previous commit.**

- If the staged changes contain multiple unrelated logical changes, split them into separate commits whenever possible.

- Do not combine unrelated fixes, features, documentation changes, dependency changes, or refactors into a single commit merely for convenience.

- Existing commit history should be treated as the project's style reference. Preserve consistency with the established Conventional Commit format.

### Commit Type Guidelines

- Use `feat` when introducing new user-visible or application functionality.
- Use `fix` when correcting incorrect or broken behavior.
- Use `refactor` when restructuring code without changing its intended behavior.
- Use `test` when adding, modifying, or improving tests.
- Use `docs` when changing documentation only.
- Use `chore` for maintenance work that does not change application behavior.
- Use `build` for dependencies, packaging, or build-system changes.
- Use `ci` for CI/CD configuration or workflow changes.
- Use `perf` for performance improvements.
- Use `style` for formatting or style-only changes.

### Examples

```text
feat(chatbot): add supplier message handling
fix(oauth): return real expires_in from refresh_access_token
fix(auth): atomically claim refresh tokens
fix(db): enforce global uniqueness on conversations
refactor(state): move ConversationState to models.enums
test(auth): cover concurrent token insertion
test(chatbot): cover webhook redelivery handling
docs(plans): document seller authentication status
build: add respx dependency
chore(git): stop tracking codebase memory artifacts
ci: update GitHub Actions workflow
```

## Python environment and test commands

This repository uses the project virtual environment at `.venv`.

Before running Python commands, use the project environment. On Windows, prefer explicit commands so the active shell environment is never ambiguous:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Rules:

- Do not run bare `pytest`, `python`, or `pip` from the global interpreter.
- Do not treat a global-environment collection/import failure as a project test failure.
- If `.venv` is missing or cannot run the required command, stop and report it; do not install dependencies globally.
- For any focused test run, use the same interpreter, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web.py
```