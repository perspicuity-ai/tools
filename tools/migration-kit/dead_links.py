#!/usr/bin/env python3
"""Report relative links that are already dead in a source tree, before any migration.

A migration is the wrong moment to discover that a link was never resolvable. This walks
one or more source directories, resolves every relative Markdown link against the real
filesystem, and reports the ones that do not land on an existing file.

Fenced code blocks are skipped, because a shell or text listing can contain bracket-and-
parenthesis shapes that are not links.

Usage:
    dead_links.py --root <repo> --path docs/research --path docs/initiatives/example [--json]
"""

import argparse
import json
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt"}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s#?]+)(?:[#?][^)\s]*)?\)")
# Any scheme-shaped target is not a file path: urn:li:organization:ID is an identifier,
# not a missing document. Resolving these against the filesystem produces false dead links.
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def strip_fences(text):
    out, inside = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return "\n".join(out)


def find_dead(repo_root, paths):
    dead, checked = [], 0
    for rel_path in paths:
        base = repo_root / rel_path
        if not base.exists():
            dead.append({"file": rel_path, "target": "(path itself missing)", "resolved": str(base)})
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if "__pycache__" in f.parts:
                continue
            try:
                text = strip_fences(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            for match in LINK_RE.finditer(text):
                target = match.group(1)
                if target.startswith("#") or SCHEME_RE.match(target):
                    continue
                checked += 1
                resolved = (f.parent / target).resolve()
                if not resolved.exists():
                    dead.append({
                        "file": f.relative_to(repo_root).as_posix(),
                        "target": target,
                        "resolved": str(resolved),
                    })
    return dead, checked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--path", action="append", required=True, help="Directory or file, relative to root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    dead, checked = find_dead(args.root.resolve(), args.path)
    if args.json:
        print(json.dumps({"checked": checked, "dead": dead}, indent=1))
    else:
        print(f"relative links checked: {checked}")
        print(f"already dead: {len(dead)}")
        for entry in dead:
            print(f"  {entry['file']}\n      {entry['target']}")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
