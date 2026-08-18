# -*- coding: utf-8 -*-
"""H2991 relay smoke — a real browser, cross-origin, before/after in one page.

Serves a page on http://127.0.0.1 (an allowlisted origin) and makes TWO real
cross-origin fetches from it:

  A. straight to https://github.com/login/device/code  -> must FAIL (no ACAO)
  B. to the nginx relay                                 -> must SUCCEED and the
                                                           body must be readable

A is the FINDINGS §477 measurement reproduced inside a browser rather than with
curl (curl ignores CORS, so it can never show this failure). B is the fix.

The probe client_id is deliberately fake: GitHub answers `{"error":"Not Found"}`,
which is a real response from GitHub and is exactly what must become readable.
Registering a real OAuth App changes the BODY, not the CORS behaviour this proves.
"""
import functools
import http.server
import socketserver
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8")

RELAY = "https://kosha.193.232.229.92.sslip.io/gh-device"
PORT = 8747
PAGE = """<!doctype html><meta charset=utf-8><title>relay probe</title><body>
<script>
window.__run = async function (url) {
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: JSON.stringify({client_id: 'Iv1.probe0000000000', scope: 'public_repo'})
    });
    return {ok: true, status: r.status, body: (await r.text()).slice(0, 120)};
  } catch (e) {
    return {ok: false, error: String(e)};
  }
};
</script></body>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
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

from playwright.sync_api import sync_playwright  # noqa: E402

fails = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    page.goto("http://127.0.0.1:%d/" % PORT)

    direct = page.evaluate("() => window.__run('https://github.com/login/device/code')")
    relayed = page.evaluate("() => window.__run('%s/code')" % RELAY)
    browser.close()

httpd.shutdown()

print("A. direct to github.com/login/device/code")
print("   %r" % (direct,))
if direct.get("ok"):
    fails.append("direct fetch SUCCEEDED — GitHub now sends CORS headers; §477 needs re-measuring "
                 "and this relay may be unnecessary")
    print("   -> UNEXPECTED: the browser could read it")
else:
    print("   -> blocked by CORS, as §477 measured  [expected]")

print()
print("B. through the relay")
print("   %r" % (relayed,))
if not relayed.get("ok"):
    fails.append("relayed fetch failed: %s" % relayed.get("error"))
    print("   -> FAIL")
else:
    print("   -> readable: HTTP %s, body %s" % (relayed["status"], relayed["body"]))
    if "error" not in relayed["body"]:
        print("   note: body is not GitHub's expected fake-client_id error")

print()
if fails:
    print("RELAY SMOKE FAILED:")
    for f in fails:
        print("  - %s" % f)
    sys.exit(1)
print("RELAY SMOKE PASS — the browser cannot read github.com directly, and can read it through the relay")
