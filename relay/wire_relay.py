# -*- coding: utf-8 -*-
"""Insert the H2991 relay include into the kosha vhost, once, before `location / {`.

Run ON THE BOX.

Transactional (bughunt 27.10.2026, finding 5). The include references a snippet AND
a map/zone pair; with either one missing, `nginx -t` is a hard error — and the old
version discovered that only AFTER it had already rewritten the vhost. Therefore:

  * preconditions first — both files must exist, else nothing is touched (exit 2);
  * `nginx -t` as a baseline before the edit, and again after it (exit 4 / exit 3);
  * a failed post-check restores the timestamped backup automatically;
  * the write is atomic (temp file in the same directory + os.replace), so a crash
    cannot leave a truncated production vhost;
  * the last line names the reload as the step still owed — "inserted" is not "live".

Idempotent: an existing uncommented include is left alone. A COMMENTED-OUT include
does not count, so re-running the script restores a deliberately disabled relay.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time

VHOST_PATH = "/etc/nginx/sites-available/kosha"
SNIPPET_PATH = "/etc/nginx/snippets/gh-device-relay.conf"
MAP_PATH = "/etc/nginx/conf.d/gh-device-relay-map.conf"
INCLUDE_LINE = "    include /etc/nginx/snippets/gh-device-relay.conf;"
ANCHOR = "    location / {"


def already_wired(src: str) -> bool:
    """True only for an ACTIVE include — a commented-out one is not wired."""
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "include" in stripped and "gh-device-relay.conf" in stripped:
            return True
    return False


def wire(src: str) -> str | None:
    """Return the vhost text with the include inserted, or None when already wired."""
    if already_wired(src):
        return None
    index = src.find(ANCHOR)
    if index < 0:
        raise ValueError("no `%s` anchor" % ANCHOR.strip())
    return src[:index] + INCLUDE_LINE + "\n" + src[index:]


def write_atomic(path, text: str) -> None:
    """Write text atomically, preserving the target's permission bits."""
    path = pathlib.Path(path)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def nginx_test(binary: str = "nginx"):
    """Run `nginx -t`. Returns None when nginx is not installed, else (ok, message)."""
    executable = shutil.which(binary)
    if not executable:
        return None
    try:
        done = subprocess.run([executable, "-t"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return done.returncode == 0, (done.stderr or done.stdout).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vhost", default=VHOST_PATH)
    parser.add_argument("--snippet", default=SNIPPET_PATH)
    parser.add_argument("--map", dest="mapconf", default=MAP_PATH)
    parser.add_argument("--no-validate", action="store_true", help="skip `nginx -t` (off-box runs)")
    args = parser.parse_args(argv)

    vhost = pathlib.Path(args.vhost)
    if not vhost.exists():
        print("FAIL: %s does not exist" % vhost)
        return 1
    src = vhost.read_text(encoding="utf-8")

    if already_wired(src):
        print("already wired — no change")
        return 0

    missing = [p for p in (args.snippet, args.mapconf) if not pathlib.Path(p).exists()]
    if missing:
        print("FAIL: missing %s" % ", ".join(missing))
        print("      the include references both; copying only one makes `nginx -t` fail after the")
        print("      rewrite. Refusing to touch %s." % vhost)
        return 2

    try:
        out = wire(src)
    except ValueError as exc:
        print("FAIL: %s in %s" % (exc, vhost))
        return 1

    if not args.no_validate:
        baseline = nginx_test()
        if baseline is None:
            print("WARN: nginx not found — skipping validation (pass --no-validate to silence)")
        elif not baseline[0]:
            print("FAIL: `nginx -t` is already red before this edit; refusing to write")
            if baseline[1]:
                print("      " + baseline[1].splitlines()[0])
            return 4

    backup = "%s.bak-%s" % (vhost, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(vhost, backup)
    print("backup: %s" % backup)

    write_atomic(vhost, out)

    if not args.no_validate:
        after = nginx_test()
        if after and not after[0]:
            shutil.copy2(backup, vhost)
            print("FAIL: `nginx -t` red after the edit — restored %s" % vhost)
            if after[1]:
                print("      " + after[1].splitlines()[0])
            return 3

    print("inserted include before `%s`" % ANCHOR.strip())
    print("NOT LIVE YET — finish with: systemctl reload nginx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
