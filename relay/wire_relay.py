# -*- coding: utf-8 -*-
"""Insert the H2991 relay include into the kosha vhost, once, before `location / {`.

Idempotent: an existing include is left alone. Writes a timestamped backup first.
Run ON THE BOX.
"""
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

PATH = "/etc/nginx/sites-available/kosha"
INCLUDE = "    include /etc/nginx/snippets/gh-device-relay.conf;\n"

src = open(PATH, encoding="utf-8").read()
if "gh-device-relay.conf" in src:
    print("already wired — no change")
    sys.exit(0)

backup = "%s.bak-%s" % (PATH, time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(PATH, backup)
print("backup: %s" % backup)

anchor = "    location / {"
i = src.find(anchor)
if i < 0:
    print("FAIL: no `location / {` anchor in %s" % PATH)
    sys.exit(1)

out = src[:i] + INCLUDE + "\n" + src[i:]
open(PATH, "w", encoding="utf-8").write(out)
print("inserted include before `location / {`")
