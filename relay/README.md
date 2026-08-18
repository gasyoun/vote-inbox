# GitHub OAuth device-flow CORS relay

_Created: 18-08-2026 · Last updated: 18-08-2026_

Live at **`https://kosha.193.232.229.92.sslip.io/gh-device`**.

## Why this exists

GitHub sends **no `Access-Control-Allow-Origin`** on its OAuth device endpoints. A
static vote sheet on [gasyoun.github.io](https://gasyoun.github.io/vote/) can *send*
the device-code request and can never *read* the reply, so the device flow — the one
browser-safe login that needs no client secret — cannot be completed by a static page
at all. This is GitHub hardening those endpoints against browser-based token theft,
not an outage, and registering an OAuth App does not change it.

Measured 18-08-2026 and written up as
[Uprava FINDINGS §477](https://github.com/gasyoun/Uprava/blob/main/FINDINGS.md):

| Probe (`Origin: https://gasyoun.github.io`) | Result |
|---|---|
| `OPTIONS github.com/login/device/code` | `404`, **no ACAO** |
| `POST github.com/login/device/code` | **no ACAO** |
| `GET api.github.com/repos/…/contents/…` | `200`, `Access-Control-Allow-Origin: *` |
| `OPTIONS` the contents `PUT` | `204`, `Authorization` allowed |

The trap is that the neighbouring API is fine — the vote hydrate and the inbox write
already work from the page. **Only token acquisition needed this.**

## What it is, and is not

It adds CORS headers and forwards. It holds **no `client_secret`** (the device flow
has none), stores nothing, and logs no body.

It is **not an authorization bypass.** Anyone may POST these two endpoints directly
with `curl`, which ignores CORS entirely; the only thing a browser lacked was
permission to read a public response. The origin allowlist is therefore the whole
access control, and it is enough. Removing this relay breaks the *Save to GitHub*
button and nothing else.

## Endpoints

| Relay path | Forwards to |
|---|---|
| `POST /gh-device/code` | `https://github.com/login/device/code` |
| `POST /gh-device/token` | `https://github.com/login/oauth/access_token` |

`GET` is refused (`403`). Allowed origins live in
[`gh-device-relay-map.conf`](gh-device-relay-map.conf): the vote hub, plus
`localhost`/`127.0.0.1` on any port for local development. An unlisted origin gets an
empty `$cors_origin`, nginx omits the header, and the browser refuses the read.

## Install

On `193.232.229.92` (nginx ≥ 1.25; no new service, no new account):

```sh
scp relay/gh-device-relay-map.conf root@193.232.229.92:/etc/nginx/conf.d/
scp relay/gh-device-relay.conf     root@193.232.229.92:/etc/nginx/snippets/
scp relay/wire_relay.py            root@193.232.229.92:/tmp/
ssh root@193.232.229.92 'python3 /tmp/wire_relay.py && nginx -t && systemctl reload nginx'
```

`wire_relay.py` inserts the `include` into the kosha vhost before its `location / {`,
is idempotent, and writes a timestamped backup first.

## Verify

```sh
python relay/smoke_relay.py     # needs playwright
```

Serves a page on an allowlisted `127.0.0.1` origin and makes two real cross-origin
fetches from one real browser: straight to `github.com` (must fail — this reproduces
§477 *inside* a browser, which `curl` can never show, since curl ignores CORS) and
through the relay (must succeed and be readable). Green 18-08-2026:

```
A. direct to github.com/login/device/code
   {'ok': False, 'error': 'TypeError: Failed to fetch'}
B. through the relay
   {'ok': True, 'status': 404, 'body': '{"error":"Not Found"}'}
```

The probe `client_id` is deliberately fake, so `{"error":"Not Found"}` is GitHub's
genuine answer — and it being *readable* is the whole point. A real OAuth App changes
that body, not the CORS behaviour.

## Still needed before the button works

**An OAuth App `client_id`.** GitHub exposes no API for creating one, so this is a
browser form a human fills in — the click path is in
[IMPLEMENTATION_UPRAVA_VOTE_PLATFORM_W3.md](https://github.com/gasyoun/Uprava/blob/main/docs/IMPLEMENTATION_UPRAVA_VOTE_PLATFORM_W3.md).
Paste the result into [`../config/oauth_client_id.txt`](../config/oauth_client_id.txt),
then generators pass:

```python
config["github_inbox"] = {
    "repo": "gasyoun/vote-inbox",
    "client_id": "<from config/oauth_client_id.txt>",
    "device_url": "https://kosha.193.232.229.92.sslip.io/gh-device",
}
```

Until both are set, csl-pyutil ships the button **disabled with an honest tooltip**
rather than as a control that cannot succeed. Leave `branch` unset — the contents API
writes to this repo's own default branch, which is `master`; guessing `main` was the
0.17.0 bug fixed in
[v0.17.1](https://github.com/sanskrit-lexicon/csl-pyutil/releases/tag/v0.17.1).

_Dr. Mārcis Gasūns_
