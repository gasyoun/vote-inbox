# -*- coding: utf-8 -*-
"""H2991 B3 live hydrate smoke — a CLEAN browser profile picks up MG's votes.

Loads the published pack-01 in a fresh Chromium context with empty localStorage.
If B3 works, the decisions saved to gasyoun/vote-inbox appear without anyone voting
in this browser — which is the cross-machine resume the whole inbox exists for.

Also loads pack-02 to prove hydration is scoped: pack 1's file must not decide
pack 2's cards.

Bughunt 27.10.2026, finding 4: the expectations used to be hardcoded against MG's
live votes ("6" approve, "10 of 22 decided"). One more vote on the published sheet
overwrites decisions/h2991_demo/pack-01.json and turns a CORRECT system red, with no
way to tell "hydration broke" from "I voted again". The counts are now derived from
the pack file this smoke ships with, so the assertion is "the page agrees with the
inbox" rather than "the page agrees with a snapshot taken on 18-08-2026".
"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACK1_PATH = ROOT / "decisions" / "h2991_demo" / "pack-01.json"

PACK1 = "https://gasyoun.github.io/vote/sheets/h2991_demo/pack-01.html"
PACK2 = "https://gasyoun.github.io/vote/sheets/h2991_demo/pack-02.html"
PARENT = "https://gasyoun.github.io/vote/sheets/h2991_demo.html"


def expected_counts(pack):
    """Derive the counters the page must show from the committed pack itself."""
    items = pack.get("items", [])
    counts = {"approve": 0, "reject": 0, "defer": 0}
    for item in items:
        decision = item.get("decision")
        if decision in counts:
            counts[decision] += 1
    counts["decided"] = sum(counts[k] for k in ("approve", "reject", "defer"))
    counts["unvoted"] = len(items) - counts["decided"]
    return counts


def check(label, got, want, fails):
    ok = got == want
    print("%s %-46s got=%r want=%r" % ("PASS" if ok else "FAIL", label, got, want))
    if not ok:
        fails.append(label)
    return ok


def main():
    try:
        pack = json.loads(PACK1_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        print("FAIL cannot read %s: %s" % (PACK1_PATH, exc))
        return 1

    want = expected_counts(pack)
    print("expectations derived from %s" % PACK1_PATH.relative_to(ROOT))
    print("  %r" % want)
    print()

    fails = []

    from playwright.sync_api import sync_playwright  # noqa: E402

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context()  # fresh profile: no localStorage, never voted here
        page = ctx.new_page()

        page.goto(PACK1)
        page.wait_for_selector(".card")
        stored = page.evaluate("() => localStorage.getItem('review-sheet:h2991_demo')")
        check("clean profile starts with no record", stored, None, fails)

        # hydrate is a network round trip: dir listing, then one file
        page.wait_for_function(
            "() => document.getElementById('c-approve').textContent !== '0'", timeout=45000)
        page.wait_for_timeout(500)

        check("pack-01 approve hydrated", page.locator("#c-approve").inner_text(), str(want["approve"]), fails)
        check("pack-01 reject hydrated", page.locator("#c-reject").inner_text(), str(want["reject"]), fails)
        check("pack-01 defer hydrated", page.locator("#c-defer").inner_text(), str(want["defer"]), fails)
        check("pack-01 nothing left unvoted", page.locator("#c-unvoted").inner_text(), str(want["unvoted"]), fails)
        note = page.locator("#inboxNote").inner_text()
        print("     inbox banner: %r" % note)
        check("banner reports the pull", "GitHub" in note, True, fails)

        page.goto(PACK2)
        page.wait_for_selector(".card")
        page.wait_for_timeout(8000)
        check("pack-02 stays unvoted (scoped)", page.locator("#c-unvoted").inner_text(), "10", fails)
        check("pack-02 approve stays 0", page.locator("#c-approve").inner_text(), "0", fails)

        page.goto(PARENT)
        page.wait_for_timeout(2000)
        parent_text = page.locator("#ovText").inner_text()
        check("parent counts pack-01's decisions", parent_text.startswith("%d of " % want["decided"]), True, fails)
        print("     parent text: %r" % parent_text)
        check("parent marks pack-01 done", page.locator("a.pack.done").count(), 1, fails)

        browser.close()

    print()
    if fails:
        print("HYDRATE SMOKE FAILED: %s" % ", ".join(fails))
        return 1
    print("HYDRATE SMOKE PASS — a browser that never voted shows the inbox's votes, scoped to pack 1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
