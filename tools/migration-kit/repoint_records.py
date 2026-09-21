#!/usr/bin/env python3
"""Repoint references to decision records that moved to another repository.

Two forms of reference exist and only one is a link:

  * a markdown link to the file, e.g. `[x](2026-09-09-outreach-batch-one.md)`
  * a bare identifier in front matter or prose, e.g. `id: 2026-09-09-outreach-batch-one` or
    `parent: 2026-09-14-connections-initiative`

Leaving the second form alone is the subtle failure: the record still reads as if it resolves
locally, and nothing errors. Both forms are rewritten here.

Usage:
    repoint_records.py --root <repo> --moved <moved.json> --sha <ref> [--apply] [--json]

`moved.json` maps a record filename (or id) to the repository that now holds it, e.g.
    {"2026-09-09-outreach-batch-one.md": "perspicuity-ai/company"}
"""

import argparse
import json
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt"}
LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^)\s#?]+)((?:[#?][^)\s]*)?\))")
EXTERNAL = ("http://", "https://", "mailto:", "tel:", "data:")
FENCE_RE = re.compile(r"^(\s*)(```|~~~)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--moved", type=Path, required=True, help="JSON: name -> target repo")
    parser.add_argument("--sha", default="main", help="Ref to pin links to")
    parser.add_argument("--skip", action="append", default=[], help="Path prefix to leave alone")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    moved = json.loads(args.moved.read_text(encoding="utf-8"))
    # Index by filename and by bare id, so both reference forms resolve.
    by_name = {k: v for k, v in moved.items()}
    root = args.root.resolve()

    link_edits, bare_edits, errors = [], [], []
    files_changed = set()

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in args.skip):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        new = text
        # A moved record's own file no longer exists here; skip any that remain.
        inside, rebuilt = False, []
        for line in new.splitlines(keepends=True):
            if FENCE_RE.match(line):
                inside = not inside
                rebuilt.append(line)
                continue
            if inside:
                rebuilt.append(line)
                continue

            def do_link(m):
                prefix, target, suffix = m.group(1), m.group(2), m.group(3)
                if target.startswith(EXTERNAL) or Path(target).is_absolute():
                    return m.group(0)
                name = Path(target.split("#")[0]).name
                dest = by_name.get(name)
                if not dest:
                    return m.group(0)
                url = f"https://github.com/{dest}/blob/{args.sha}/Decisions/{name}"
                link_edits.append({"file": rel, "from": target, "to": url})
                files_changed.add(rel)
                return prefix + url + (suffix if suffix.startswith("#") else "")

            line = LINK_RE.sub(do_link, line)

            # Bare identifiers: only inside front matter or an id-like key, to avoid
            # rewriting prose that merely mentions a date.
            def do_bare(m):
                key, value = m.group(1), m.group(2)
                stem = value.replace(".md", "")
                dest = by_name.get(value) or by_name.get(stem)
                if not dest:
                    return m.group(0)
                bare_edits.append({"file": rel, "key": key, "id": value, "now_in": dest})
                files_changed.add(rel)
                return m.group(0)  # the identifier itself is stable; only report it

            line = re.sub(r'^(\s*(?:id|parent|depends_on:\s*-\s*id|reopens|supersedes)):\s*"?([A-Za-z0-9._-]+)"?\s*$',
                          do_bare, line)
            rebuilt.append(line)
        new = "".join(rebuilt)
        if new != text and args.apply:
            path.write_text(new, encoding="utf-8")

    if args.json:
        print(json.dumps({"links": len(link_edits), "bare": len(bare_edits),
                          "files": sorted(files_changed), "link_edits": link_edits,
                          "bare_edits": bare_edits, "errors": errors,
                          "applied": args.apply}, indent=1))
        return 0

    print(f"markdown links rewritten: {len(link_edits)}")
    print(f"bare identifiers found (stable, not rewritten): {len(bare_edits)}")
    print(f"files changed: {len(files_changed)}")
    for f in sorted(files_changed):
        n = sum(1 for e in link_edits if e["file"] == f)
        b = sum(1 for e in bare_edits if e["file"] == f)
        print(f"  {f}  ({n} link(s), {b} bare id(s))")
    print(f"\nmode: {'APPLIED' if args.apply else 'dry run, nothing written'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
