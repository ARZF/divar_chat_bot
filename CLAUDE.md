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
