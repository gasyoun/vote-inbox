# -*- coding: utf-8 -*-
"""H2991 B3 live hydrate smoke — a CLEAN browser profile picks up MG's votes.

Loads the published pack-01 in a fresh Chromium context with empty localStorage.
If B3 works, the ten decisions MG saved to gasyoun/vote-inbox appear without
anyone voting in this browser — which is the cross-machine resume the whole
inbox exists for.

Also loads pack-02 to prove hydration is scoped: pack 1's file must not decide
pack 2's cards.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

PACK1 = "https://gasyoun.github.io/vote/sheets/h2991_demo/pack-01.html"
PACK2 = "https://gasyoun.github.io/vote/sheets/h2991_demo/pack-02.html"
PARENT = "https://gasyoun.github.io/vote/sheets/h2991_demo.html"

fails = []


def check(label, got, want):
    ok = got == want
    print("%s %-46s got=%r want=%r" % ("PASS" if ok else "FAIL", label, got, want))
    if not ok:
        fails.append(label)


from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context()  # fresh profile: no localStorage, never voted here
    page = ctx.new_page()

    page.goto(PACK1)
    page.wait_for_selector(".card")
    stored = page.evaluate("() => localStorage.getItem('review-sheet:h2991_demo')")
    check("clean profile starts with no record", stored, None)

    # hydrate is a network round trip: dir listing, then one file
    page.wait_for_function(
        "() => document.getElementById('c-approve').textContent !== '0'", timeout=45000)
    page.wait_for_timeout(500)

    check("pack-01 approve hydrated", page.locator("#c-approve").inner_text(), "6")
    check("pack-01 reject hydrated", page.locator("#c-reject").inner_text(), "3")
    check("pack-01 defer hydrated", page.locator("#c-defer").inner_text(), "1")
    check("pack-01 nothing left unvoted", page.locator("#c-unvoted").inner_text(), "0")
    note = page.locator("#inboxNote").inner_text()
    print("     inbox banner: %r" % note)
    check("banner reports the pull", "GitHub" in note, True)

    page.goto(PACK2)
    page.wait_for_selector(".card")
    page.wait_for_timeout(8000)
    check("pack-02 stays unvoted (scoped)", page.locator("#c-unvoted").inner_text(), "10")
    check("pack-02 approve stays 0", page.locator("#c-approve").inner_text(), "0")

    page.goto(PARENT)
    page.wait_for_timeout(2000)
    check("parent reads 10 of 22", page.locator("#ovText").inner_text(), "10 of 22 decided")
    check("parent marks pack-01 done", page.locator("a.pack.done").count(), 1)

    browser.close()

print()
if fails:
    print("HYDRATE SMOKE FAILED: %s" % ", ".join(fails))
    sys.exit(1)
print("HYDRATE SMOKE PASS — a browser that never voted shows MG's votes, scoped to pack 1")
