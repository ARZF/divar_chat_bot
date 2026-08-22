# Phase 4 — AI Integration (Not Started)

> **Agent rule:** Do not create `services/ai.py` or any LLM imports before this phase.

- [ ] Create `services/ai.py` with `ask_llm(prompt: str, history: list[dict]) -> str`
- [ ] LLM provider: OpenAI-compatible endpoint (configurable via `settings.llm_base_url`)
- [ ] Add to `Settings`: `llm_api_key: str`, `llm_base_url: str`, `llm_model: str`
- [ ] Trigger AI only when state machine returns `FALLBACK` — not for menu-routed intents
- [ ] Per-tenant rate limit: max 20 AI calls / tenant / hour (in-memory, Redis in future)
- [ ] Prompt template in a separate `prompts/` directory, not hardcoded in `ai.py`

# Phase 5 — Interactive Buttons (Not Started)

> **Agent rule:** Do not begin until `PLAN.md`'s Active Phase reads `Phase 3`.

- [ ] Build `build_button_payload(labels: list[str]) -> dict` utility
- [ ] Send buttons via Divar message payload structure (refer to Divar API docs)
- [ ] Handle `button_click` action type in webhook alongside text messages — this is why
      `schemas/webhook.py` was given the `new_chatbot_message.type` field back in Phase 1;
      use it here to distinguish `TEXT` from button-click events
