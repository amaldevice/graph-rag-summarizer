# Slice breakdown — multi-provider LLM fallback for summarization runs

Date: 2026-07-05
Status: Published as issues #18 and #19
Parent PRD issue: #17

## Slices

1. **#18 — Ship provider-routed map summarization with Groq, Gemini, NVIDIA NIM, and OpenRouter fallback**
   - Blocked by: None
   - Covers user stories: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 22, 23, 24, 25, 26, 28, 30

2. **#19 — Reuse the shared provider session for final reduction**
   - Blocked by: #18
   - Covers user stories: 13, 14, 15, 21, 24, 25, 26, 28, 29, 30

## Notes

- Slice 1 carries the new provider router, env contract, fallback policy, retry policy, logging contract, and first end-to-end summarization path.
- Slice 2 completes the run-scoped Shared LLM Session behavior by ensuring final reduction inherits sticky failover state instead of re-resolving providers independently.
- Relation extraction stays outside this slice set by design and remains a later follow-up if multi-provider structured-output behavior is needed.
