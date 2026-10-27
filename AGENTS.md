# AGENTS.md — vote-inbox

_Created: 20-09-2026 · Last updated: 27-10-2026 (bughunt fix lane: the validation command now exists and is enforced in CI)_

- **Purpose:** drop point for `/review-sheet` pack decisions — `decisions/<sheet_id>/pack-NN.json`, ids + verdicts only, never card text; Uprava's `tools/review_decisions_watcher.py` merges complete packs back into the owning repo.
- **Key commands:** `python3 tools/validate_packs.py` before push (exits 1 on any pack that does not match `schema/decisions-pack.schema.json`); `git pull --rebase` before writing (small fast-moving repo, branch `master`); `python3 -m unittest discover -s tests` for the relay/schema suite. CI (`.github/workflows/tests.yml`) runs both, so a bad pack can no longer land.
- **Owner:** @gasyoun (a human decides; execution via Uprava handoffs).

_Гасунс_
