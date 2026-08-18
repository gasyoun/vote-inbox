# vote-inbox

_Created: 18-08-2026 · Last updated: 18-08-2026_

Drop point for [`/review-sheet`](https://github.com/gasyoun/claude-config/blob/main/commands/review-sheet.md)
pack decisions — **ids and verdicts only**, never card text.

## What this holds

`decisions/<sheet_id>/pack-NN.json` — one file per voted pack of a review
sheet. A repo's `tools/review_decisions_watcher.py`
([Uprava](https://github.com/gasyoun/Uprava)) fetches this repo, merges every
complete pack for a `sheet_id`, and writes the cumulative decisions file back
into the owning repo.

## Pack schema

See [`schema/decisions-pack.schema.json`](https://github.com/gasyoun/vote-inbox/blob/master/schema/decisions-pack.schema.json).
Shape:

```json
{
  "sheet_id": "h215-gold-full-320-2026-08-14",
  "pack": 1,
  "pack_size": 10,
  "generated": "17-08-2026",
  "decided": 10,
  "items": [{"id": "…", "decision": "approve", "reject_label": null, "note": ""}]
}
```

## What is NEVER in a pack file

- No `question` field, no card HTML, no gloss text, no personal names.
- `note` is capped at 280 characters and must not contain `<` or a
  `question` dump — the consuming tool refuses a pack that violates this
  (default on ambiguity: truncate the note, keep the verdict, log it).

## Publishing a pack

A pack lands here either via the hub's **Save to GitHub** button (device
flow, `public_repo` scope only — no `client_secret` is ever stored in any
repo) or by hand-committing a JSON file matching the schema above. Client id
for the OAuth app lives in
[`config/oauth_client_id.txt`](https://github.com/gasyoun/vote-inbox/blob/master/config/oauth_client_id.txt)
once registered by a human.

## License

[CC0](https://github.com/gasyoun/vote-inbox/blob/master/LICENSE) — the ids
and verdicts here carry no creative content worth protecting.

_Dr. Mārcis Gasūns_
