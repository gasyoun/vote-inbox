# AGENTS.md — vote-inbox

_Created: 20-09-2026 · Last updated: 20-09-2026_

- **Purpose:** drop point for `/review-sheet` pack decisions — `decisions/<sheet_id>/pack-NN.json`, ids + verdicts only, never card text; Uprava's `tools/review_decisions_watcher.py` merges complete packs back into the owning repo.
- **Key commands:** validate packs against `schema/decisions-pack.schema.json` before push; `git pull --rebase` before writing (small fast-moving repo, branch `master`).
- **Owner:** @gasyoun (a human decides; execution via Uprava handoffs).

_Гасунс_
