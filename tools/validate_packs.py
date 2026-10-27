# -*- coding: utf-8 -*-
"""Validate every committed decision pack against schema/decisions-pack.schema.json.

The repo's AGENTS.md tells every agent to validate packs before pushing. Until
now that instruction had no command behind it, and 6 of the 9 committed packs
violated the schema (bughunt 27.10.2026, finding 3). This is the command.

Usage:
    python3 tools/validate_packs.py                 # validate decisions/**/pack-*.json
    python3 tools/validate_packs.py path/to/pack.json ...
    python3 tools/validate_packs.py --quiet         # one line per failure only

Exit: 0 every pack valid · 1 at least one pack invalid · 2 schema unreadable
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schema" / "decisions-pack.schema.json"


def load_schema(path: pathlib.Path = SCHEMA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(pack: dict, schema: dict) -> list[str]:
    """Return a list of human-readable violations; empty means valid."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - CI installs requirements-dev.txt
        return ["jsonschema is not installed (pip install -r requirements-dev.txt)"]

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(pack), key=lambda e: list(e.path))
    out = []
    for err in errors:
        where = "/".join(str(p) for p in err.path) or "<root>"
        out.append("%s: %s" % (where, err.message))
    return out


def pack_paths(args: list[str]) -> list[pathlib.Path]:
    if args:
        return [pathlib.Path(a) for a in args]
    return sorted((ROOT / "decisions").glob("*/pack-*.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("packs", nargs="*", help="pack files (default: decisions/**/pack-*.json)")
    parser.add_argument("--quiet", action="store_true", help="print failures only")
    args = parser.parse_args(argv)

    try:
        schema = load_schema()
    except (OSError, json.JSONDecodeError) as exc:
        print("SCHEMA UNREADABLE: %s" % exc, file=sys.stderr)
        return 2

    paths = pack_paths(args.packs)
    if not paths:
        print("no packs found", file=sys.stderr)
        return 1

    failed = 0
    for path in paths:
        rel = path.relative_to(ROOT) if path.is_absolute() and ROOT in path.parents else path
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print("FAIL %s — unreadable: %s" % (rel, exc))
            failed += 1
            continue
        errors = validate(pack, schema)
        if errors:
            failed += 1
            print("FAIL %s" % rel)
            for err in errors:
                print("      - %s" % err)
        elif not args.quiet:
            print("OK   %s" % rel)

    print("\n%d of %d packs valid" % (len(paths) - failed, len(paths)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
