# Plan 007: Add test coverage for the chatbot intent router

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `advisor-plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat f5abbbc..HEAD -- services/chatbot.py`
> If `services/chatbot.py` changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/001 (test tooling must exist first)
- **Category**: tests
- **Planned at**: commit `f5abbbc`, 2026-07-23

## Why this matters

`services/chatbot.py` is the core product logic — it decides what the bot says to
every customer — yet **no test references `services.chatbot`**. Untested behavior
includes: `/start` touchpoint parsing (`parse_start_message`), intent matching
(`_match_intent`), pure-greeting detection (`_is_pure_greeting`), product-name
extraction (`_extract_product_name`), and the price-reply formatting in
`_handle_price_intent`. A regression in any of these silently breaks every
seller's bot. This plan adds characterization + unit tests for the pure functions
first (cheap, high-value, no DB), establishing coverage on the highest-risk
untested module.

## Assumptions

- Plan 001 has landed: `pytest`, `pytest-asyncio`, `pytest-mock`, `aiosqlite` are
  installed and a `conftest.py` sets the required env vars. If not, STOP and run
  plan 001 first.
- The pure helper functions in `services/chatbot.py` can be tested without a DB or
  network (they operate on strings and the in-memory price cache).
- `_handle_price_intent` reads the module-level price cache
  (`services.price_lookup._cache`) and can be seeded the same way
  `tests/test_price_lookup.py` does (see "Current state").

If any assumption proves false, treat it as a STOP condition.

## Current state

**Pure/near-pure functions in `services/chatbot.py`** (test these — no DB needed):

- `parse_start_message(text) -> Optional[Tuple[str, Optional[str]]]` (lines 33-58):
  returns `(touchpoint, token_or_none)` for `/start <TOUCHPOINT> [<token>]`, else
  `None`. Touchpoints: `MY_POST, MY_DIVAR, DIVAR_PRO, CHAT, DEMAND_POST`
  (`TOUCHPOINT_NAMES`, lines 28-30). Bare `/start MY_DIVAR` (no token) is valid.
- `_match_intent(normalized_text) -> Optional[str]` (lines 167-173): splits into
  tokens, returns `"PRICE"|"WARRANTY"|"SUPPORT"` if any keyword token matches
  `settings.KEYWORD_MAP`, else `None`. KEYWORD_MAP (`config.py:72-76`):
  `{price,قیمت}→PRICE`, `{warranty,گارانتی}→WARRANTY`, `{support,پشتیبانی}→SUPPORT`.
- `_is_pure_greeting(normalized_text) -> bool` (lines 176-181): True only if EVERY
  token is in `settings.GREETING_TOKENS` (`config.py:44-46`:
  `سلام,درود,سلامت,هلو,hi,hello,hey`); empty → False.
- `_extract_product_name(normalized_text) -> str` (lines 184-192): drops `قیمت`/
  `price` and `settings.FILTERED_KEYWORDS`, returns the remaining joined string.
- `_handle_price_intent(client_id, normalized_text) -> str` (lines 278-325):
  builds the price reply. Uses the price cache via `get_all_matching_prices`,
  `get_price`, `find_top_matches`. Returns `PRICE_PROMPT_MESSAGE` when no product
  name; single/bulk/fuzzy/suggestion/not-found branches otherwise.

**Note on normalization**: intent functions receive text that has already been
through `normalize_text` (from `services/price_lookup.py`). In tests, call
`normalize_text` first (import it) to mirror the real call path.

**Price-cache seeding pattern** (copy from `tests/test_price_lookup.py:49-60`):
```python
import services.price_lookup as pl
pl._cache[CID] = pl.ClientPriceCache(
    prices={"iphone 13": 35000000},
    canonical_names={"iphone 13": "iPhone 13"},
    product_names=["iphone 13"],
)
# ... test ...
pl._cache.pop(CID, None)   # cleanup
```

**Repository conventions**:
- Tests live in `tests/test_<module>.py`, class-grouped (`class TestX:`), plain
  `assert` (see `tests/test_price_lookup.py:89`).
- Env vars are set by `conftest.py` (after plan 001) — new test files do NOT need
  the inline `os.environ.setdefault` block.
- Async endpoint/DB tests use the in-memory SQLite + `TestClient` pattern in
  `tests/test_auth.py:74-90` (only needed if you test `handle_bot_reply` end-to-end).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Run new tests | `pytest tests/test_chatbot.py` | all pass |
| Run full suite | `pytest` | exit 0, all pass |

## Scope

**In scope** (the only file you should create):
- `tests/test_chatbot.py` (create) — unit tests for the functions listed above

**Out of scope** (do NOT touch):
- `services/chatbot.py` — this plan only *adds tests*; do not modify source to
  make it more testable unless a STOP-condition forces a report first.
- The async `handle_bot_reply` orchestrator DB flow — an end-to-end test of it is
  a valuable follow-up but is explicitly deferred here to keep this plan focused
  and DB-free. (Plan 004 adds its own targeted `_safe_send` test.)

## Git workflow

- Branch: `advisor/007-chatbot-tests`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Create tests/test_chatbot.py with parse_start_message coverage

Create `tests/test_chatbot.py`. Import the functions under test and
`normalize_text`. No inline env block (conftest.py handles it). Add a
`TestParseStartMessage` class covering:
- `/start MY_POST tok123` → `("MY_POST", "tok123")`
- `/start DEMAND_POST tok456` → `("DEMAND_POST", "tok456")`
- bare `/start MY_DIVAR` → `("MY_DIVAR", None)`
- `/start DIVAR_PRO` → `("DIVAR_PRO", None)`
- `/start CHAT convid` → `("CHAT", "convid")`
- unknown touchpoint `/start BOGUS x` → `None`
- non-start text `"hello"` → `None`
- empty string `""` → `None`
- leading/trailing whitespace `"  /start MY_DIVAR  "` → `("MY_DIVAR", None)`
  (function calls `.strip()`)

**Verify**: `pytest tests/test_chatbot.py -k ParseStart` → all pass.

### Step 2: Add intent + greeting + extraction coverage

Add classes `TestMatchIntent`, `TestIsPureGreeting`, `TestExtractProductName`.
Because these expect normalized input, run inputs through `normalize_text` in the
test (import it from `services.chatbot` or `services.price_lookup`). Cover:

`TestMatchIntent`:
- `normalize_text("قیمت آیفون")` → `_match_intent(...)` == `"PRICE"`
- `"گارانتی"` → `"WARRANTY"`
- `"پشتیبانی"` → `"SUPPORT"`
- `"price iphone"` → `"PRICE"` (English keyword)
- `"سلام"` → `None` (no intent keyword)

`TestIsPureGreeting`:
- `"سلام"` → True
- `"hi"` → True
- `"سلام قیمت"` → False (not every token is a greeting)
- `""` → False (empty)

`TestExtractProductName`:
- `normalize_text("قیمت آیفون ۱۳")` → strips `قیمت` → contains `iphone` and `13`
  (verify the filtered word `قیمت` is gone; assert on the remaining tokens)
- `"قیمت"` alone → `""` (only the keyword, nothing left)

**Verify**: `pytest tests/test_chatbot.py -k "Intent or Greeting or Extract"` →
all pass.

### Step 3: Add _handle_price_intent coverage (seeded cache, no DB)

Add `TestHandlePriceIntent`. Use a fixture that seeds
`services.price_lookup._cache[CID]` (pattern from "Current state") and pops it on
teardown. Import `_handle_price_intent` and `normalize_text` from
`services.chatbot`. Use a fixed `CID = 1`. Cover:
- **No product name**: `_handle_price_intent(CID, normalize_text("قیمت"))` ==
  `settings.PRICE_PROMPT_MESSAGE`.
- **Single substring match**: seed `{"iphone 13": 35000000}`; query
  `normalize_text("قیمت iphone 13")` → reply contains `iPhone 13` and `35,000,000`.
- **Not found**: seed a catalog without the queried product; query an unrelated
  product → reply == `settings.PRICE_NOT_FOUND_MESSAGE` (assuming no fuzzy/suggest
  hit; pick a query dissimilar enough — e.g. a nonsense string).

Keep assertions on substrings (formatted numbers use `,` thousands separators:
`f"{price:,}"`). Import `settings` from `config`.

**Verify**: `pytest tests/test_chatbot.py -k PriceIntent` → all pass.

### Step 4: Run the full suite

```bash
pytest
```

**Verify**: Exit code 0, all tests pass including the new `tests/test_chatbot.py`
(aim for ~20+ new test cases across the four classes).

## Test plan

- New file `tests/test_chatbot.py`, structured after `tests/test_price_lookup.py`
  (class-grouped, plain `assert`, module-level `CID`, cache fixture with teardown).
- Cases enumerated per step above: parse (9), intent (5), greeting (4),
  extraction (2), price-intent (3+).
- Verification: `pytest tests/test_chatbot.py` → all pass; `pytest` → full suite
  green.

## Done criteria

- [x] `tests/test_chatbot.py` exists and imports from `services.chatbot`
- [x] `parse_start_message` covered (all 5 touchpoints, bare, unknown, empty, whitespace)
- [x] `_match_intent`, `_is_pure_greeting`, `_extract_product_name` each covered
- [x] `_handle_price_intent` covered for prompt / single-match / not-found (plus bulk-list)
- [x] Price-cache fixture seeds and tears down `services.price_lookup._cache[CID]`
- [x] `pytest tests/test_chatbot.py` passes (32); `pytest` (full) exits 0 (120 passed)
- [x] No source files modified — only `tests/test_chatbot.py` + this plan's README row (`git status`)
- [x] `advisor-plans/README.md` row 007 status updated

**Executed 2026-07-29** on branch `advisor/007-chatbot-tests`. Deviations from the
plan as written, both forced by drift since `f5abbbc`:

1. `tests/test_chatbot.py` **already existed** (216 lines, covering
   `parse_start_message` + `_resolve_new_conversation` + `_lookup_conversation`),
   so this was an *append*, not a create. The monolithic
   `test_parse_start_message_supports_all_touchpoints` was replaced by the
   `TestParseStartMessage` class, which is a strict superset of its asserts.
2. `_handle_price_intent` is now **async** with signature
   `(db, client_id, normalized_text)` — `db` was added and `get_price` is awaited
   with it. Tests were written against the live signature; `services/chatbot.py`
   was **not** modified (per STOP conditions).

Also removed the 14-line inline `os.environ.setdefault` block that plan 001's
`conftest.py` rendered redundant, and added `Product.__table__` to the existing
SQLite `session_factory` fixture instead of standing up a second engine.
No real bugs surfaced in the router.

## STOP conditions

Stop and report back if:

- Plan 001's test tooling is absent (no `pytest`/`conftest.py`) — run 001 first.
- Any function's signature or behavior differs from the "Current state" excerpts
  (drift — re-read the function before writing its test).
- A test reveals what looks like a *real bug* in `services/chatbot.py` (e.g. an
  intent misclassification) — do NOT fix the source; report the failing case and
  the observed vs. expected behavior so it can be triaged as a separate finding.
- `_handle_price_intent`'s fuzzy/suggestion branches make the "not found" case
  hard to trigger deterministically — report; pick a query that reliably scores
  below `settings.SUGGESTION_MIN_SCORE` rather than guessing.

## Maintenance notes

- This plan deliberately covers the *pure* logic. A valuable follow-up is an
  end-to-end async test of `handle_bot_reply` (conversation resolution, welcome-
  on-first-message, unresolved path) using the in-memory SQLite fixture from
  `tests/test_auth.py:74-90` and mocking `divar_service.send_message`.
- When intents, greeting tokens, or filtered keywords change in `config.py`, these
  tests may need updating — they encode the current keyword sets.
- A reviewer should check that the price-cache fixture always pops `_cache[CID]` on
  teardown, so tests don't leak state into `tests/test_price_lookup.py`.
