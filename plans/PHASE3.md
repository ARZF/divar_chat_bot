# Phase 3 — Interactive Buttons (Not Started)

> **Agent rule:** Do not begin until `PLAN.md`'s Active Phase reads `Phase 3`.

- [ ] Build `build_button_payload(labels: list[str]) -> dict` utility
- [ ] Send buttons via Divar message payload structure (refer to Divar API docs)
- [ ] Handle `button_click` action type in webhook alongside text messages — this is why
      `schemas/webhook.py` was given the `new_chatbot_message.type` field back in Phase 1;
      use it here to distinguish `TEXT` from button-click events
