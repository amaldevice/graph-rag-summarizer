# Slice breakdown — cross-platform local embedding runtime

Date: 2026-07-04
Parent PRD issue: #6

## Slices

1. **#7 — Codify the cross-platform embedding runtime contract**
   - Blocked by: None
   - Covers user stories: 3, 4, 5, 6, 16, 17, 20

2. **#8 — Route the default sentence-transformers path through the shared embedding resolver**
   - Blocked by: #7
   - Covers user stories: 1, 2, 13, 14, 15, 16, 17

3. **#9 — Add an optional ONNX embedding path with lazy local preparation**
   - Blocked by: #7, #8
   - Covers user stories: 7, 8, 9, 10, 11, 12, 19

4. **#10 — Document and regression-test the cross-platform embedding runtime**
   - Blocked by: #8, #9
   - Covers user stories: 18, 20

## Notes

- Default backend remains `sentence-transformers`.
- macOS prefers `mps` and falls back to `cpu`.
- Windows and Linux stay conservative on `cpu` by default.
- ONNX remains optional and experimental in this pass.
- All local embedding artifacts live under `.cache/embedding/` and must not be committed.
