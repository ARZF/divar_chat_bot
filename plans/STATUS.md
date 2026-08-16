# Current Status

| Phase | Status |
|-------|--------|
| Phase 1 | Complete — all bugfixes (1.B1, 1.B2, 1.B3) resolved |
| Phase 2 | In Progress — **2.2 (models), 2.7 (admin & seller endpoints), 2.3 (Divar API-key/OAuth service), 2.1 (conversation→client resolution), 2.4 (price cache), 2.5 (background task / session lifetime), and 2.6 (state machine) done. 2.8 partial — OTP/SMS deferred; see CHECKLISTS.md. 2.9 (supplier-wide chat) substantially implemented 2026-08-16 but NOT complete — 1 item still open: the `/oauth/dev/start` scopes. The `refresh_access_token()` per-seller defect found in that audit is fixed, along with the event re-registration on refresh (see PHASE2.md §2.9). Next: 2.7 admin rework. 2.5 was satisfied as a side effect of 2.1/2.4's implementation, not a separate pass — its test-coverage gap was closed 2026-08-03; 2.6 was wired 2026-08-11. See CHANGELOG.md.** Build order: ~~2.2~~ → 2.8 partial → ~~2.7~~ → ~~2.3~~ → (~~2.1~~ ∥ ~~2.4~~ ∥ ~~2.6~~) → ~~2.5~~ → 2.9 partial → 2.7 admin rework |
| Phase 3 | Not Started |
| Phase 4 | Not Started |