# -*- coding: utf-8 -*-
"""H2991 relay smoke — a real browser, cross-origin, before/after in one page.

Serves a page on http://127.0.0.1 (an allowlisted origin) and makes real
cross-origin fetches from it:

  A. straight to https://github.com/login/device/code  -> must FAIL (no ACAO)
  B. to the nginx relay with the FAKE client id         -> must be readable, and the
                                                           body must be GitHub's JSON
                                                           error — an nginx 502 page is
                                                           a FAILURE, not a note
  C. to the nginx relay with the REAL client id         -> must be readable and carry a
     (config/oauth_client_id.txt)                          device_code. This is the call
                                                           that exposes the proxy-buffer
                                                           502; the fake-id path never can.

Then, without a browser, it asserts the allowlist itself:

  D. OPTIONS with the allowlisted Origin    -> 204 and Access-Control-Allow-Origin set
  E. OPTIONS with an unlisted Origin        -> 204 and NO Access-Control-Allow-Origin
  F. GET                                    -> refused

Bughunt 27.10.2026, findings 1-2: the previous version sent only the fake id, never
looked at the status, and printed a "note" for any body that did not contain the
string "error" — so the exact regression this smoke exists to catch (a 502 from an
undersized proxy buffer) passed green. Verified live 27.10.2026: the fake id answers
`{"error":"Not Found"}` in 21 bytes, the real id answers a 165-byte device-code JSON
behind GitHub's full header set.

Needs: playwright (browser part) and network access to the relay.
"""
import http.server
import json
import pathlib
import socketserver
import sys
import threading
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

RELAY = "https://kosha.193.232.229.92.sslip.io/gh-device"
FAKE_CLIENT_ID = "Iv1.probe0000000000"
ALLOWED_ORIGIN = "https://gasyoun.github.io"
UNLISTED_ORIGIN = "https://bughunt-probe.invalid"
PORT = 8747
CLIENT_ID_PATH = pathlib.Path(__file__).resolve().parent.parent / "config" / "oauth_client_id.txt"

PAGE = """<!doctype html><meta charset=utf-8><title>relay probe</title><body>
<script>
window.__run = async function (url, clientId) {
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: JSON.stringify({client_id: clientId, scope: 'public_repo'})
    });
    return {ok: true, status: r.status, body: (await r.text()).slice(0, 300)};
  } catch (e) {
    return {ok: false, error: String(e)};
  }
};
</script></body>"""


def read_client_id(path=CLIENT_ID_PATH):
    """The public OAuth client id shipped in config/; None when the file is absent."""
    try:
        client_id = pathlib.Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return client_id or None


def _json(text):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def classify_device(status, body):
    """A real device-code reply: 2xx AND a JSON object carrying device_code."""
    if not (200 <= int(status) < 300):
        return False, "HTTP %s (expected 2xx)" % status
    payload = _json(body)
    if payload is None:
        return False, "body is not JSON — %r" % (body or "")[:80]
    if "device_code" not in payload:
        return False, "JSON without device_code: %r" % payload
    return True, "HTTP %s, device_code %s…" % (status, str(payload["device_code"])[:8])


def classify_error(status, body):
    """GitHub's answer to the fake id: a JSON object with `error`, and not a 5xx."""
    if int(status) >= 500:
        return False, "HTTP %s is a relay/upstream failure, not GitHub's answer" % status
    payload = _json(body)
    if payload is None:
        return False, "body is not JSON — %r" % (body or "")[:80]
    if "error" not in payload:
        return False, "JSON without `error`: %r" % payload
    return True, "HTTP %s, error=%r" % (status, payload["error"])


def origin_allowed(headers, origin):
    """True only when the response names EXACTLY this origin in ACAO (case-insensitive lookup)."""
    acao = None
    for key, value in headers.items():
        if key.lower() == "access-control-allow-origin":
            acao = value
            break
    return acao == origin


def preflight(url, origin, method="OPTIONS", timeout=30):
    """Issue a request and return (status, lowercased headers). Never raises on 4xx/5xx."""
    request = urllib.request.Request(
        url,
        method=method,
        headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}


def serve_page():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def browser_checks(client_id):
    """Returns (results, fails). results is a list of (label, detail).

    A missing playwright or a missing browser binary is a FAIL with a clear remedy,
    not a traceback — and it does not stop the browser-free allowlist checks, which
    main() runs first.
    """
    results, fails = [], []
    try:
        from playwright.sync_api import sync_playwright  # noqa: E402
    except ImportError as exc:
        return results, ["playwright is not installed (%s) — pip install playwright && playwright install" % exc]

    httpd = serve_page()
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as exc:  # noqa: BLE001 - any launch failure is "cannot test"
                first = str(exc).splitlines()[0]
                return results, [
                    "playwright could not launch a browser (%s) — run `playwright install chromium`" % first
                ]
            page = browser.new_page()
            page.goto("http://127.0.0.1:%d/" % PORT)
            direct = page.evaluate("() => window.__run('https://github.com/login/device/code', %s)" % _js(FAKE_CLIENT_ID))
            fake = page.evaluate("() => window.__run('%s/code', %s)" % (RELAY, _js(FAKE_CLIENT_ID)))
            real = None
            if client_id:
                real = page.evaluate("() => window.__run('%s/code', %s)" % (RELAY, _js(client_id)))
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()

    results.append(("A. direct to github.com (must be CORS-blocked)", repr(direct)[:160]))
    if direct.get("ok"):
        fails.append(
            "direct fetch SUCCEEDED — GitHub now sends CORS headers; §477 needs re-measuring "
            "and this relay may be unnecessary"
        )

    results.append(("B. relay, fake client id (must be GitHub's JSON error)", repr(fake)[:160]))
    if not fake.get("ok"):
        fails.append("relayed fake-id fetch failed at the browser: %s" % fake.get("error"))
    else:
        ok, detail = classify_error(fake.get("status"), fake.get("body", ""))
        results.append(("   -> classify_error", detail))
        if not ok:
            fails.append("fake-id path: %s" % detail)

    if real is None:
        results.append(("C. relay, real client id", "SKIPPED — no %s" % CLIENT_ID_PATH.name))
        fails.append(
            "C SKIPPED: %s is missing, so the call that exposes the proxy-buffer 502 was not made"
            % CLIENT_ID_PATH
        )
    else:
        results.append(("C. relay, real client id (must carry a device_code)", repr(real)[:160]))
        if not real.get("ok"):
            fails.append("relayed real-id fetch failed at the browser: %s" % real.get("error"))
        else:
            ok, detail = classify_device(real.get("status"), real.get("body", ""))
            results.append(("   -> classify_device", detail))
            if not ok:
                fails.append("real-id path: %s" % detail)

    return results, fails


def _js(value):
    return json.dumps(value)


def allowlist_checks():
    results, fails = [], []

    status, headers = preflight(RELAY + "/code", ALLOWED_ORIGIN)
    results.append(("D. OPTIONS, allowlisted origin", "HTTP %s, ACAO %r" % (status, headers.get("access-control-allow-origin"))))
    if status != 204:
        fails.append("allowlisted preflight answered HTTP %s (expected 204)" % status)
    if not origin_allowed(headers, ALLOWED_ORIGIN):
        fails.append("allowlisted origin did not get its own ACAO back")

    status, headers = preflight(RELAY + "/code", UNLISTED_ORIGIN)
    results.append(("E. OPTIONS, unlisted origin (must get NO ACAO)", "HTTP %s, ACAO %r" % (status, headers.get("access-control-allow-origin"))))
    if origin_allowed(headers, UNLISTED_ORIGIN):
        fails.append(
            "UNLISTED origin %s received Access-Control-Allow-Origin — the allowlist is open" % UNLISTED_ORIGIN
        )

    status, headers = preflight(RELAY + "/code", ALLOWED_ORIGIN, method="GET")
    results.append(("F. GET (must be refused)", "HTTP %s" % status))
    if status != 403:
        fails.append("GET answered HTTP %s (expected 403)" % status)

    return results, fails


def main(argv=None):
    client_id = read_client_id()

    print("client id: %s" % ("(real, from config/) " + client_id[:6] + "…" if client_id else "MISSING"))
    print()

    fails = []

    # D-F first: they need no browser, so an operator without playwright still gets
    # the access-control verdict instead of nothing at all.
    results, list_fails = allowlist_checks()
    fails += list_fails
    for label, detail in results:
        print("  %-56s %s" % (label, detail))
    print()

    results, browser_fails = browser_checks(client_id)
    fails += browser_fails
    for label, detail in results:
        print("  %-56s %s" % (label, detail))
    print()

    if fails:
        print("RELAY SMOKE FAILED:")
        for failure in fails:
            print("  - %s" % failure)
        return 1
    print("RELAY SMOKE PASS — the browser cannot read github.com directly and can read it through")
    print("the relay; the real client id yields a device_code; the allowlist admits only its own")
    print("origin and refuses GET")
    return 0


if __name__ == "__main__":
    sys.exit(main())
