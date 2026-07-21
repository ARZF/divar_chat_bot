# Phase 4 — AI Integration (Not Started)

> **Agent rule:** Do not create `services/ai.py` or any LLM imports before this phase.

- [ ] Create `services/ai.py` with `ask_llm(prompt: str, history: list[dict]) -> str`
- [ ] LLM provider: OpenAI-compatible endpoint (configurable via `settings.llm_base_url`)
- [ ] Add to `Settings`: `llm_api_key: str`, `llm_base_url: str`, `llm_model: str`
- [ ] Trigger AI only when state machine returns `FALLBACK` — not for menu-routed intents
- [ ] Per-tenant rate limit: max 20 AI calls / tenant / hour (in-memory, Redis in future)
- [ ] Prompt template in a separate `prompts/` directory, not hardcoded in `ai.py`
