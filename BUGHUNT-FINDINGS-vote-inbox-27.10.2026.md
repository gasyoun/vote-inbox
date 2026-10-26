# BUGHUNT-FINDINGS — vote-inbox — 27.10.2026

_Created: 27-10-2026 · Author: Dr. Mārcis Gasūns (DeepSeek Flash, `deepseek-flash`, via DSH) · Run: interactive day `/bughunt` (night driver provider-blocked: `opencode` cooled until 27.10 03:44, `zai-coding-plan` until 27.10 05:36 — cursor not advanced by the driver)_

**Elapsed:** ~22 min. Budget 40 min; nothing failed three times.
**Scope:** the repo's executable and declarative surface — `relay/` (3 Python scripts + 2 nginx confs), `schema/`, `decisions/**` (9 packs), `.github/workflows/`. Read-only static hunt plus live probes against the deployed relay. My own probes wrote nothing; the single state-changing live call was the device-code issuance the README documents as its own verification (it yields an unused code that expires in 899 s).

## Summary

| # | Sev | Finding | Where |
|---|-----|---------|-------|
| 1 | MEDIUM | `smoke_relay.py` **cannot fail on the 502 regression it exists to catch**: it still probes with a fake `client_id`, never asserts the status, and turns a non-GitHub body into a printed *note* instead of a failure | [`relay/smoke_relay.py:26,35,86-95`](https://github.com/gasyoun/vote-inbox/blob/master/relay/smoke_relay.py#L26-L95) |
| 2 | MEDIUM | The origin allowlist — the only thing that stops an arbitrary page from reading a device-flow token — is **never tested**; every assertion comes from an allowlisted origin | [`relay/gh-device-relay-map.conf:9-13`](https://github.com/gasyoun/vote-inbox/blob/master/relay/gh-device-relay-map.conf#L9-L13), [`relay/smoke_relay.py:71`](https://github.com/gasyoun/vote-inbox/blob/master/relay/smoke_relay.py#L71) |
| 3 | MEDIUM | **6 of 9 committed packs violate the repo's own schema**, and the live emitter violates it further — the schema matches a producer generation that no longer exists, and the reconciling GTD row was archived undone | [`schema/decisions-pack.schema.json:7-8,25-29`](https://github.com/gasyoun/vote-inbox/blob/master/schema/decisions-pack.schema.json#L7-L29), [`decisions/**`](https://github.com/gasyoun/vote-inbox/tree/master/decisions) |
| 4 | LOW | `smoke_hydrate.py` pins **live mutable vote counts** (`6/3/1`, `10 of 22`), so one more vote on the published sheet turns a correct system red | [`relay/smoke_hydrate.py:16-18,47-64`](https://github.com/gasyoun/vote-inbox/blob/master/relay/smoke_hydrate.py#L47-L64) |
| 5 | LOW | `wire_relay.py` rewrites a production vhost **non-transactionally**, validates nothing, and reports success before the config is live | [`relay/wire_relay.py:16-33`](https://github.com/gasyoun/vote-inbox/blob/master/relay/wire_relay.py#L16-L33) |

**No HIGH finding.** The relay itself is correct in production: allowlisted `OPTIONS` returns `204` + `Access-Control-Allow-Origin`, an unlisted origin gets the other headers but **no** `ACAO`, `GET` is `403`, the fake id gets `404`, and the real id returns a real `device_code` with **no 502** — so the `proxy_buffer_size 32k` fix holds today. All five findings sit in the *verification and contract* layer, which is why they are worth fixing: this repo's product is a gate (a vote that must be readable, a schema a consumer can trust), and both currently certify more than they check.

## 1. MEDIUM — the relay smoke still walks into the trap its own README documents

`smoke_relay.py` did not change when the OAuth App was registered; it still sends the deliberately fake id and still reasons only about `ok`:

```python
RELAY = "https://kosha.193.232.229.92.sslip.io/gh-device"     # :26
body: JSON.stringify({client_id: 'Iv1.probe0000000000', ...   # :35  fake id
...
if not relayed.get("ok"):                                     # :88  only failure branch
    fails.append(...)
else:
    print("   -> readable: HTTP %s, body %s" % (...))
    if "error" not in relayed["body"]:                         # :93
        print("   note: body is not GitHub's expected fake-client_id error")   # NOTE, not a fail
```

Measured today, same endpoint, two bodies:

```bash
$ curl -X POST ... -d '{"client_id":"Iv1.probe0000000000"}' $U/code      # what the smoke sends
{"error":"Not Found"}                       [http 404 | 21 bytes]
$ curl -X POST ... -d '{"client_id":"<from config/oauth_client_id.txt>"}' $U/code
{"device_code":"…","user_code":"A0BD-6F58",…}   [http 200 | 165 bytes, plus GitHub's ~4 KB header set]
```

The smoke sees `ok: true` for **any** response the fetch can read, because it never looks at `status`. Revert `proxy_buffer_size 32k` and nginx answers `502` with an HTML error page: the fetch succeeds, `"error"` is not in that body, the script prints the note and **exits 0**. That is verbatim the failure the README records under "The trap: a smoke that passes on the error path" — the config was fixed, the *test* was not, and it is still driven by a 21-byte error response while `config/oauth_client_id.txt` (public by design, it ships in every sheet) sits unused beside it.

**Impact:** the only automated check on the relay certifies a state in which every real login 502s. A regression introduced by an nginx update, a config re-copy from a template, or a new vhost build passes green.

**Fix direction:** send the committed client id (keep the fake id as a second, explicitly expected-`404` call), assert `status` and that the body parses as JSON, and make any body that is neither GitHub's `{"error":…}` nor a `device_code` JSON a `fails.append`.

## 2. MEDIUM — the access control is asserted nowhere

`gh-device-relay-map.conf` is explicit that the map *is* the control:

```nginx
# An origin absent from this map gets an EMPTY $cors_origin, and nginx omits a
# header whose value is the empty string — so an unlisted page still cannot read
# the reply. That is the whole access control this relay has …
map $http_origin $cors_origin {
    default                                       "";
    "https://gasyoun.github.io"                   $http_origin;
    "~^http://(127\.0\.0\.1|localhost)(:[0-9]+)?$" $http_origin;
}
```

The smoke's page is served on `http://127.0.0.1` — an allowlisted origin — and both fetches come from it. Nothing anywhere sends an unlisted `Origin`. Probed live today:

| Probe | Result |
|---|---|
| `OPTIONS`, `Origin: https://gasyoun.github.io` | `204` + `Access-Control-Allow-Origin: https://gasyoun.github.io` |
| `OPTIONS`, `Origin: https://evil.example` | `204`, methods/headers/max-age present, **no `Access-Control-Allow-Origin`** ✅ |

So the control is correct right now and nobody would know if it stopped being correct. Because MG's `client_id` is public and embedded in every published sheet, an open map is not merely cosmetic: it would let *any* host serve the device-code form and read back the token the voter authorised — the exact hand-off the allowlist exists to confine to `gasyoun.github.io`.

**Fix direction:** one extra call from a non-allowlisted origin, asserting the ACAO header is **absent** while the request is otherwise served. It belongs in the same script as an explicit negative control.

## 3. MEDIUM — the schema is wrong about the data it governs

`schema/decisions-pack.schema.json` requires `pack_size`, forbids extra properties, and demands `generated` as `DD-MM-YYYY`. Validating the repo's own committed packs against it:

```
FAIL decisions/h2991_demo/pack-01.json
      - 'pack_size' is a required property
      - generated: '2026-08-18T12:54:33.744Z' does not match '^\d{2}-\d{2}-\d{4}$'
OK   …/round1-goals-40/pack-01.json   OK pack-02   OK pack-03
FAIL …/round1-goals-40/pack-04.json   - pack_size missing · reviewedAt unexpected · generated ISO
FAIL …/round2-architecture-40/pack-01.json … pack-04.json   (same three, ×4)
```

**6 of 9 fail.** Three producer generations are visible in `decisions/`:

| Generation | Commits | Shape |
|---|---|---|
| `render_review_sheet` path | round1 packs 01–03 | DMY `generated`, `pack_size`, `note`/`reject_label` — **schema-conformant** (3/9) |
| browser "Save to GitHub" | round1-04, round2 ×4 | ISO `generated`, `reviewedAt`, **no `pack_size`** (6/9) |
| the live emitter today | `gasyoun.github.io/vote` sheet, fetched 27-10 | ISO `generated`, `reviewedAt`, **`time_total_seconds`**, per-item **`time_seconds`**, no `pack_size` |

The live payload, verbatim from the published sheet:

```js
return JSON.stringify({ sheet_id: SHEET_ID, generated: nowIso, reviewedAt: nowIso, decided: decided,
  time_total_seconds: __timeTotal(), items: ids.map(function (id) { … return { id: id,
  decision: rec.decision || null, note: rec.note || '', time_seconds: __timeFor(id) }; }) }, null, 2);
```

Two of those extras are *deliberate measurement*, not accident: Uprava's changelog records csl-pyutil 0.23.0 adding `reviewedAt` for the S6 vote-leg timestamps (29-08-2026), and the same S6 work established that base-mode `generated` is the **vote** moment, not issuance — while this schema still describes `generated` as "when the pack HTML was emitted". So the contract is stale on three counts: a field the emitter stopped sending, two fields it now always sends, and a semantic the estate already re-decided in writing.

**This is a known-but-lost row, not a new discovery.** Uprava's archived GTD (`GTD_ARCHIVE-2026-09-p3.md:1102`, 05-09-2026) states it exactly: *"the client envelope carries ISO `generated` + `reviewedAt` but omits required `pack_size` … Next: add `pack_size` to `__inboxPayload`, reconcile the schema with the retained `reviewedAt` measurement, and pin a browser-payload schema test."* No open GTD row carries it today — archived without being done, and every write since has re-violated the schema.

The repo's own [`AGENTS.md`](https://github.com/gasyoun/vote-inbox/blob/master/AGENTS.md) instructs every agent, as a *key command*: «validate packs against `schema/decisions-pack.schema.json` before push». Today that instruction is unsatisfiable — an agent that follows it must either refuse to push a pack the emitter just produced, or learn to ignore the check. A trap for both humans and agents, in one line of onboarding.

**Impact:** the only documented contract for consumers outside this repo rejects 6 of its 9 packs and 100 % of future ones. Any gate added tomorrow (the natural fix for §5) is red on landing, which is how a schema gets deleted instead of enforced.

**Fix direction:** decide one canonical shape — the evidence says the emitter's (`ISO generated` = vote moment, `reviewedAt`, optional `time_total_seconds`/`time_seconds`, `pack_size` back into `__inboxPayload`) — rewrite the schema to it, then add a CI job validating `decisions/**`. The six extant offenders either get `pack_size` backfilled from `len(items)` or a dated grandfather list.

## 4. LOW — the hydrate smoke is data-coupled to MG's votes

```python
check("pack-01 approve hydrated", page.locator("#c-approve").inner_text(), "6")   # :47
check("pack-01 reject hydrated",  …                                     , "3")
check("pack-01 defer hydrated",   …                                     , "1")
check("parent reads 10 of 22",    …, "10 of 22 decided")                          # :63
```

Those numbers are the contents of [`decisions/h2991_demo/pack-01.json`](https://github.com/gasyoun/vote-inbox/blob/master/decisions/h2991_demo/pack-01.json) — a live file that the published sheet overwrites every time MG presses **Сохранить в GitHub**. One more vote and a correct hydrate reports `got=7 want=6`; the operator cannot tell "hydration broke" from "I voted again", which is the shape that gets a smoke relaxed until it passes.

**Fix direction:** read the pack file in the script and derive the expected counts from it (`approve = sum(d == "approve")`, `unvoted = pack_size − decided`), so the smoke asserts *agreement with the inbox* rather than with a snapshot.

## 5. LOW — `wire_relay.py` is not transactional and reports success early

```python
src = open(PATH, encoding="utf-8").read()           # :16  /etc/nginx/sites-available/kosha
... shutil.copy2(PATH, backup)                      # :22
out = src[:i] + INCLUDE + "\n" + src[i:]            # :31
open(PATH, "w", encoding="utf-8").write(out)        # :32  truncate then write
print("inserted include before `location / {`")     # :33  success message
```

The README's install line is safe (`python3 /tmp/wire_relay.py && nginx -t && systemctl reload nginx`), but the script's own docstring says "Run ON THE BOX" and it is shipped alone to `/tmp`, so the `&&` chain is the operator's discipline, not the script's guarantee. Four consequences:

- **No preconditions.** The snippet it includes references `limit_req zone=gh_device` and `$cors_origin`, both defined only in the map conf. With the map conf absent, `nginx -t` fails *after* the vhost has already been rewritten — a config that cannot be reloaded, left on disk, with the backup sitting beside it unused.
- **No validation, no reload.** `nginx -t` and `systemctl reload nginx` are the README's next steps; the script prints success while the live config is unchanged. "Inserted" is reported as "wired".
- **Non-atomic write.** `open(PATH,'w')` truncates before writing; a crash mid-write leaves a truncated vhost (nginx keeps serving the old one, so the damage surfaces at the *next* reload, far from the cause).
- **Idempotence by substring.** `if "gh-device-relay.conf" in src` is true for a commented-out `# include …`, so a deliberately disabled include reads as "already wired".

**Fix direction:** assert the snippet + map conf exist, `nginx -t` **before** the edit as a baseline, write to a temp file in the same directory and `os.replace`, `nginx -t` after, and print an explicit `systemctl reload nginx` as the remaining manual step (or take `--reload`).

## What verified green (live, this run)

- **Relay in production**: allowlisted `OPTIONS` → `204` + ACAO; unlisted origin → `204`, no ACAO; `GET /code` → `403`; `POST` fake id → `404 {"error":"Not Found"}`; `POST` real id → `200` with `device_code`/`user_code` **and no 502** (`proxy_buffer_size 32k` holds; the header wall is real — 165-byte body rides a ~4 KB header set).
- `python3 -m py_compile relay/*.py` → rc 0.
- All 11 tracked JSON files parse.
- The three `round1` packs 01–03 validate clean against the schema (they are the `render_review_sheet` generation).
- `decided` equals the non-null item count in all 9 packs; no duplicate ids in any pack; per-item `note` values are ≤280 chars with no `<`.
- The privacy claim holds in the data: no pack carries card/question text, and the only free-text is a one-line curator note.

## Residual actions (a hunt reports; the fix lane executes)

1. **Harden `smoke_relay.py`** — real client id + status/body assertions + the unlisted-origin negative control (findings 1–2).
2. **Reconcile `schema/decisions-pack.schema.json` to the live emitter**, restore `pack_size` in `__inboxPayload`, and add a CI `schema` job validating `decisions/**` (finding 3).
3. **De-couple `smoke_hydrate.py`** from a vote snapshot — derive expectations from the pack file (finding 4).
4. **Make `wire_relay.py` transactional** — preconditions, `nginx -t` either side, atomic replace, explicit reload step (finding 5).

Per the skill's fix-lane contract these are minted as GTD rows in the same pass (see the PR body for the ids), not left implicit here.

## Why this repo needed the pass at all

`.github/workflows/` contains exactly one workflow — Dependabot auto-merge. Nothing compiles the Python, parses the JSON, or validates a pack against `schema/`, which is why finding 3 survived seven weeks of writes and four archived GTD rows. A `schema` + `py_compile` job is the cheapest item on this list and the one that keeps the other four from recurring.

_Dr. Mārcis Gasūns_
