# Slice breakdown — profile-driven single launcher

Date: 2026-07-05
Status: Published as issues #14, #15, and #16
Parent PRD issue: #13

## Slices

1. **#14 — Ship a Query-Only Run through the single launcher**
   - Blocked by: None
   - Covers user stories: 1, 2, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 28, 29, 31, 32, 34, 35

2. **#15 — Extend the single launcher to Ingest Runs with PDF selection and collection safety guards**
   - Blocked by: #14
   - Covers user stories: 1, 2, 3, 6, 7, 8, 9, 10, 13, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 32, 33, 34, 35

3. **#16 — Extend the single launcher to Full-Pipeline Runs with availability checks and optional local PDF enrichment**
   - Blocked by: #14
   - Covers user stories: 1, 2, 5, 6, 7, 8, 9, 10, 12, 13, 18, 19, 20, 26, 27, 28, 29, 30, 32, 34, 35

## Notes

- Slice 1 carries the launcher contract, profile semantics, non-interactive behavior, and Query-Only output contract because that is the smallest end-to-end path that proves the new launcher shape.
- Slice 2 and Slice 3 both reuse the same launcher shell instead of introducing separate mode-specific entrypoints.
- The future shared-collection-safe multi-document ingest improvement remains outside this slice set and stays tracked separately in issue `#12`.
