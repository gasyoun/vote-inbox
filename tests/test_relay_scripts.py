# -*- coding: utf-8 -*-
"""The relay scripts' judgement, pinned (bughunt 27.10.2026, findings 1, 2, 4, 5).

Before this file the three relay scripts were top-level code with no importable
surface, so nothing could test them:

* ``smoke_relay.py`` treated any readable body as success —  a 502 HTML page from
  nginx printed a *note* and exited 0 (finding 1), and the origin allowlist was
  never exercised at all (finding 2).
* ``smoke_hydrate.py`` compared against MG's live vote counts (finding 4).
* ``wire_relay.py`` rewrote a production vhost in place, unvalidated (finding 5).

Every test here runs offline; the only server is a localhost fixture.
"""
import contextlib
import http.server
import io
import json
import pathlib
import stat
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "relay"))

import smoke_hydrate  # noqa: E402
import smoke_relay  # noqa: E402
import wire_relay  # noqa: E402

NGINX_502_HTML = (
    "<html>\r\n<head><title>502 Bad Gateway</title></head>\r\n<body>\r\n"
    "<center><h1>502 Bad Gateway</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n"
)
DEVICE_OK = '{"device_code":"d1","user_code":"A0BD-6F58","expires_in":899,"interval":5}'
GH_ERROR = '{"error":"Not Found"}'


class ClassifyDeviceTest(unittest.TestCase):
    """Finding 1: a 502 HTML body must FAIL, not print a note."""

    def test_real_device_response_passes(self):
        ok, detail = smoke_relay.classify_device(200, DEVICE_OK)
        self.assertTrue(ok, detail)

    def test_nginx_502_html_fails(self):
        ok, detail = smoke_relay.classify_device(502, NGINX_502_HTML)
        self.assertFalse(ok, "a 502 HTML page was accepted: %r" % detail)

    def test_html_with_200_fails(self):
        ok, _ = smoke_relay.classify_device(200, NGINX_502_HTML)
        self.assertFalse(ok, "a non-JSON body was accepted")

    def test_github_error_body_fails_the_device_expectation(self):
        ok, _ = smoke_relay.classify_device(404, GH_ERROR)
        self.assertFalse(ok, "the fake-id error body must not satisfy the device expectation")

    def test_json_without_device_code_fails(self):
        ok, _ = smoke_relay.classify_device(200, '{"message":"ok"}')
        self.assertFalse(ok, "JSON without device_code was accepted")


class ClassifyErrorTest(unittest.TestCase):
    """The fake-id call is expected to answer GitHub's JSON error — and only that."""

    def test_github_json_error_passes(self):
        ok, detail = smoke_relay.classify_error(404, GH_ERROR)
        self.assertTrue(ok, detail)

    def test_nginx_502_html_fails(self):
        ok, _ = smoke_relay.classify_error(502, NGINX_502_HTML)
        self.assertFalse(ok, "an nginx error page was accepted as GitHub's answer")

    def test_json_error_with_5xx_fails(self):
        ok, _ = smoke_relay.classify_error(503, GH_ERROR)
        self.assertFalse(ok, "a 5xx carrying a JSON body is a relay failure, not GitHub's answer")


class AllowlistTest(unittest.TestCase):
    """Finding 2: the allowlist is the control; it must be asserted, not assumed."""

    def test_allowlisted_origin_gets_acao(self):
        headers = {"access-control-allow-origin": "https://gasyoun.github.io"}
        self.assertTrue(smoke_relay.origin_allowed(headers, "https://gasyoun.github.io"))

    def test_unlisted_origin_gets_no_acao(self):
        headers = {"access-control-allow-methods": "POST, OPTIONS"}
        self.assertFalse(smoke_relay.origin_allowed(headers, "https://evil.example"))

    def test_foreign_acao_does_not_count(self):
        headers = {"access-control-allow-origin": "https://evil.example"}
        self.assertFalse(
            smoke_relay.origin_allowed(headers, "https://gasyoun.github.io"),
            "an ACAO naming a different origin must not satisfy the allowlist check",
        )

    def test_header_lookup_is_case_insensitive(self):
        headers = {"Access-Control-Allow-Origin": "https://gasyoun.github.io"}
        self.assertTrue(smoke_relay.origin_allowed(headers, "https://gasyoun.github.io"))


class _Fixtures:
    """A localhost server that answers with whatever ACAO the test wants."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        acao = None

        def do_OPTIONS(self):  # noqa: N802
            self.send_response(204)
            if self.acao:
                self.send_header("Access-Control-Allow-Origin", self.acao)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.end_headers()

        def log_message(self, *a):
            pass

    @classmethod
    def serve(cls, acao):
        handler = type("H", (cls._Handler,), {"acao": acao})
        httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        cls._httpd = httpd
        return "http://127.0.0.1:%d" % httpd.server_address[1]

    @classmethod
    def stop(cls):
        cls._httpd.shutdown()
        cls._httpd.server_close()


class PreflightTest(unittest.TestCase):
    """preflight() reads the real headers, so the allowlist check has something to read."""

    def test_preflight_returns_status_and_headers(self):
        base = _Fixtures.serve("https://gasyoun.github.io")
        try:
            status, headers = smoke_relay.preflight(base + "/code", "https://gasyoun.github.io")
        finally:
            _Fixtures.stop()
        self.assertEqual(status, 204)
        self.assertTrue(smoke_relay.origin_allowed(headers, "https://gasyoun.github.io"))

    def test_preflight_sees_an_absent_acao(self):
        base = _Fixtures.serve(None)
        try:
            status, headers = smoke_relay.preflight(base + "/code", "https://evil.example")
        finally:
            _Fixtures.stop()
        self.assertEqual(status, 204)
        self.assertFalse(smoke_relay.origin_allowed(headers, "https://evil.example"))


class ClientIdTest(unittest.TestCase):
    def test_committed_client_id_is_readable(self):
        cid = smoke_relay.read_client_id(ROOT / "config" / "oauth_client_id.txt")
        self.assertTrue(cid and not cid.startswith("Iv1."), "expected the real public client id, got %r" % cid)

    def test_missing_file_yields_none(self):
        self.assertIsNone(smoke_relay.read_client_id(ROOT / "config" / "does-not-exist.txt"))


class HydrateExpectationsTest(unittest.TestCase):
    """Finding 4: expectations come from the pack file, not from a vote snapshot."""

    def test_counts_are_derived_from_the_pack(self):
        pack = {
            "sheet_id": "s",
            "pack": 1,
            "pack_size": 4,
            "decided": 3,
            "generated": "2026-09-05T10:07:11.700Z",
            "items": [
                {"id": "D01", "decision": "approve"},
                {"id": "D02", "decision": "reject"},
                {"id": "D03", "decision": "approve"},
                {"id": "D04", "decision": None},
            ],
        }
        counts = smoke_hydrate.expected_counts(pack)
        self.assertEqual(counts["approve"], 2)
        self.assertEqual(counts["reject"], 1)
        self.assertEqual(counts["defer"], 0)
        self.assertEqual(counts["decided"], 3)
        self.assertEqual(counts["unvoted"], 1)

    def test_real_committed_pack_is_consistent(self):
        """The smoke's own pack must satisfy the derivation (guards drift in the fixture)."""
        pack = json.loads((ROOT / "decisions" / "h2991_demo" / "pack-01.json").read_text(encoding="utf-8"))
        counts = smoke_hydrate.expected_counts(pack)
        self.assertEqual(counts["decided"], pack["decided"])
        self.assertEqual(sum(counts[k] for k in ("approve", "reject", "defer")), pack["decided"])
        self.assertEqual(counts["unvoted"], len(pack["items"]) - pack["decided"])


class WireRelayTest(unittest.TestCase):
    """Finding 5: preconditions, idempotence, atomic write, rollback."""

    VHOST = "server {\n    listen 80;\n    location / {\n        proxy_pass http://app;\n    }\n}\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.vhost = self.dir / "kosha"
        self.vhost.write_text(self.VHOST, encoding="utf-8")
        self.snippet = self.dir / "gh-device-relay.conf"
        self.snippet.write_text("location = /gh-device/code { }\n", encoding="utf-8")
        self.mapconf = self.dir / "gh-device-relay-map.conf"
        self.mapconf.write_text("map $http_origin $cors_origin { }\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def main(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()):
            return wire_relay.main(
                ["--vhost", str(self.vhost), "--snippet", str(self.snippet), "--map", str(self.mapconf), "--no-validate"]
                + list(extra)
            )

    def test_commented_include_is_not_wired(self):
        src = "server {\n    # include /etc/nginx/snippets/gh-device-relay.conf;\n}\n"
        self.assertFalse(wire_relay.already_wired(src), "a commented-out include must read as NOT wired")

    def test_real_include_is_wired(self):
        src = "server {\n    include /etc/nginx/snippets/gh-device-relay.conf;\n}\n"
        self.assertTrue(wire_relay.already_wired(src))

    def test_wire_inserts_once_before_the_anchor(self):
        out = wire_relay.wire(self.VHOST)
        self.assertIsNotNone(out)
        self.assertEqual(out.count("include /etc/nginx/snippets/gh-device-relay.conf;"), 1)
        self.assertLess(out.index("gh-device-relay.conf"), out.index("location / {"))
        self.assertIsNone(wire_relay.wire(out), "second pass must be a no-op")

    def test_missing_anchor_leaves_the_file_untouched(self):
        self.vhost.write_text("server { listen 80; }\n", encoding="utf-8")
        rc = self.main()
        self.assertEqual(rc, 1)
        self.assertEqual(self.vhost.read_text(encoding="utf-8"), "server { listen 80; }\n")

    def test_missing_snippet_refuses_before_writing(self):
        self.snippet.unlink()
        rc = self.main()
        self.assertEqual(rc, 2)
        self.assertEqual(self.vhost.read_text(encoding="utf-8"), self.VHOST)
        self.assertEqual(list(self.dir.glob("kosha.bak-*")), [], "a refused run must not write a backup")

    def test_missing_map_conf_refuses_before_writing(self):
        self.mapconf.unlink()
        rc = self.main()
        self.assertEqual(rc, 2)
        self.assertEqual(self.vhost.read_text(encoding="utf-8"), self.VHOST)

    def test_successful_run_wires_backs_up_and_leaves_no_temp_file(self):
        rc = self.main()
        self.assertEqual(rc, 0)
        text = self.vhost.read_text(encoding="utf-8")
        self.assertIn("include /etc/nginx/snippets/gh-device-relay.conf;", text)
        backups = list(self.dir.glob("kosha.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), self.VHOST)
        leftovers = [p.name for p in self.dir.iterdir() if p.name.startswith(".kosha.")]
        self.assertEqual(leftovers, [], "atomic write left a temp file behind")

    def test_second_run_is_a_no_op(self):
        self.assertEqual(self.main(), 0)
        before = self.vhost.read_text(encoding="utf-8")
        self.assertEqual(self.main(), 0)
        self.assertEqual(self.vhost.read_text(encoding="utf-8"), before)

    def test_write_atomic_preserves_mode_and_replaces_content(self):
        target = self.dir / "perm"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o640)
        wire_relay.write_atomic(target, "new")
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)


if __name__ == "__main__":
    unittest.main()
