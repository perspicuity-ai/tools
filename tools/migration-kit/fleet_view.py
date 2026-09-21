#!/usr/bin/env python3
"""Read open work across several repository roots in one view.

The project's own reader is deliberately per-root: it searches declared sources inside one
repository and excludes nested projects. That is correct for working in a repository and
useless for seeing the whole portfolio, which is why this exists.

It does not reimplement the reader. It loads the installed `perspicuity_dashboard.work`
module and calls `scan()` once per root, so the rules for what counts as a record, what
"due" means and what counts as unclassified stay in one place.

Two things this refuses to do, on purpose:

  * it never writes anything, so it cannot become a second store;
  * it never merges private and public material into one artifact. Every row carries its
    root's declared visibility, and `--public-only` filters to roots marked public, so a
    view intended for publication cannot silently carry private records.

Usage:
    fleet_view.py [--config fleet.json] [--public-only] [--due] [--json]
    fleet_view.py --init-config          # write a starter config listing discovered roots

Roots are discovered from the config. Without one, `--init-config` discovers sibling
directories that contain a git repository and proposes a source layout for each.
"""

import argparse
import json
import sys
from pathlib import Path

# The reader's own defaults. A root that uses a different layout must declare it, or the
# reader finds nothing there; that is the behaviour this view exists to surface.
DEFAULT_SOURCES = ("Decisions", "docs/initiatives", "docs/outreach")

VISIBILITY = ("private", "public")


def load_reader(skill_root):
    """Load the project's work reader, preferring an explicit checkout over any install."""
    candidates = []
    if skill_root:
        candidates.append(Path(skill_root) / "skills" / "perspicuity" / "scripts")
    candidates.append(Path(__file__).resolve().parent / "reader")
    for path in candidates:
        if (path / "perspicuity_dashboard").is_dir():
            sys.path.insert(0, str(path))
            break
    try:
        from perspicuity_dashboard import work  # noqa: PLC0415
    except ImportError as error:
        raise SystemExit(
            "Cannot find the Perspicuity reader. Pass --skill-root pointing at the "
            f"perspicuity checkout, or place a copy under ./reader. ({error})"
        )
    return work


def discover_roots(parent):
    """Propose a config for sibling directories that are git repositories."""
    roots = []
    for child in sorted(Path(parent).iterdir()):
        if not (child / ".git").exists():
            continue
        declared, present = [], []
        for source in DEFAULT_SOURCES:
            if (child / source).exists():
                present.append(source)
        # A repository whose records sit directly in docs/ needs that declared instead.
        if not present and (child / "docs").is_dir():
            declared = ["docs"]
        roots.append({
            "name": child.name,
            "path": str(child),
            "sources": declared or present or list(DEFAULT_SOURCES),
            "visibility": "private",
            "declared": bool(declared or present),
        })
    return {"roots": roots}


def scan_root(work, entry):
    root = Path(entry["path"]).expanduser()
    if not root.is_dir():
        return {"name": entry["name"], "path": str(root), "visibility": entry.get("visibility", "private"),
                "error": "path does not exist", "records": []}
    sources = entry.get("sources") or list(DEFAULT_SOURCES)
    try:
        result = work.scan(str(root), sources=sources)
    except Exception as error:  # noqa: BLE001 - report, never crash the whole view
        return {"name": entry["name"], "path": str(root), "visibility": entry.get("visibility", "private"),
                "error": f"{type(error).__name__}: {error}", "records": []}

    # A record that has been migrated into another unit can still be present here, because
    # replacing it with a pointer may be deferred while inbound links still point at it.
    # Excluding it by prefix keeps the count honest without hiding the duplication: the
    # excluded records are reported and labelled with the root that now owns them.
    exclude_field = entry.get("exclude") or []
    excluded_for = {}
    if isinstance(exclude_field, str):
        exclude_field = [exclude_field]
    kept, moved = [], []
    for record in result.get("records", []):
        owner = None
        for pattern in exclude_field:
            if isinstance(pattern, dict):
                prefix, slug = pattern.get("prefix", ""), pattern.get("now_in", "another unit")
            else:
                prefix, slug = pattern, "another unit"
            if prefix and str(record.get("path", "")).startswith(prefix):
                owner = slug
                break
        if owner:
            moved.append({"path": record.get("path"), "now_in": owner})
        else:
            kept.append(record)

    return {
        "name": entry["name"],
        "path": str(root),
        "visibility": entry.get("visibility", "private"),
        "declared_sources": sources,
        "coverage": result.get("coverage", {}),
        "records": kept,
        "superseded": moved,
        "issues": result.get("issues", []),
        "exclusions": len(result.get("exclusions", [])),
    }


def is_open(record):
    return str(record.get("record_status", "")).lower() == "open"


def summarise(scans, as_of):
    """Count open work per root.

    Due dates come from the reader's normalised `next_check_date`, not from the prose
    `next_check` field, which often carries a sentence rather than a date. An earlier
    version compared the prose field as a string and reported zero due records while the
    reader itself was reporting ten.
    """
    rows = []
    for scan in scans:
        open_records = [r for r in scan.get("records", []) if is_open(r)]
        scheduled = [r for r in open_records if r.get("next_check_date")]
        due = [r for r in scheduled if str(r["next_check_date"]) <= str(as_of)]
        unscheduled = [r for r in open_records if not r.get("next_check_date")]
        waiting = [r for r in open_records if str(r.get("work_status", "")).lower() == "waiting"]
        blocked = [r for r in open_records if r.get("blocked")]
        needs_you = [r for r in open_records if r.get("queue_state") == "needs_you"]
        rows.append({
            "name": scan["name"],
            "visibility": scan["visibility"],
            "path": scan["path"],
            "error": scan.get("error"),
            "declared_sources": scan.get("declared_sources"),
            "markdown_files": (scan.get("coverage") or {}).get("markdown_files"),
            "unclassified": (scan.get("coverage") or {}).get("unclassified_records"),
            "records": len(scan.get("records", [])),
            "superseded": len(scan.get("superseded") or []),
            "superseded_items": sorted({(i["path"], i["now_in"]) for i in (scan.get("superseded") or [])}),
            "open": len(open_records),
            "due": len(due),
            "unscheduled": len(unscheduled),
            "waiting": len(waiting),
            "blocked": len(blocked),
            "needs_you": len(needs_you),
            "due_items": [{"path": r.get("path"),
                           "next_check_date": r.get("next_check_date"),
                           "check_status": r.get("check_status"),
                           "work_status": r.get("work_status"),
                           "queue_state": r.get("queue_state"),
                           "next": (r.get("next") or "")[:110]}
                          for r in sorted(due, key=lambda r: str(r.get("next_check_date")))],
        })
    return rows


def print_markdown(rows, as_of, public_only):
    scope = "public roots only" if public_only else "all roots"
    print(f"# Open work across repositories\n\nAs of {as_of}. Scope: {scope}. "
          "Read-only view; it holds no records of its own.\n")
    print("| Repository | Visibility | Records | Open | Due | No date | Waiting | Blocked | Needs you | Superseded | Sources declared |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        if row["error"]:
            print(f"| {row['name']} | {row['visibility']} | — | — | — | — | — | — | — | — | ERROR: {row['error']} |")
            continue
        print(f"| {row['name']} | {row['visibility']} | {row['records']} | {row['open']} | {row['due']} | "
              f"{row['unscheduled']} | {row['waiting']} | {row['blocked']} | {row['needs_you']} | "
              f"{row['superseded']} | {', '.join(row['declared_sources'] or [])} |")
    total_due = sum(r["due"] for r in rows if not r["error"])
    total_open = sum(r["open"] for r in rows if not r["error"])
    print(f"\n**{total_due} of {total_open} open record(s) due on or before {as_of}.** "
          "Records with no usable date are counted separately, not treated as due.")
    for row in rows:
        if not row.get("due_items"):
            continue
        print(f"\n### {row['name']} ({row['visibility']})")
        for item in row["due_items"]:
            print(f"\n- `{item['path']}` — due {item['next_check_date']}, {item['work_status']}, "
                  f"{item['queue_state']}")
            if item["next"]:
                print(f"  Next: {item['next']}")
    empty = [r["name"] for r in rows if not r["error"] and r["records"] == 0]
    if empty:
        print(f"\nNo records found in: {', '.join(empty)}. "
              "That usually means the source layout is not declared for that root, or the unit holds no "
              "`perspicuity-work/1` record yet — not that it has no work.")
    superseded = [(row["name"], path, owner) for row in rows for path, owner in row.get("superseded_items", [])]
    if superseded:
        print("\n### Superseded copies, counted once above")
        print("\nThese records exist in two roots because material was migrated before the source was "
              "replaced by a pointer. They are excluded from the owning root's counts and listed here so "
              "the duplication stays visible.")
        for name, path, owner in superseded:
            print(f"\n- `{name}` still holds `{path}`, now owned by **{owner}**")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="JSON file listing roots")
    parser.add_argument("--parent", type=Path, default=Path.home() / "projects",
                        help="Where to look when discovering roots (default ~/projects)")
    parser.add_argument("--skill-root", type=Path, help="Path to a perspicuity checkout holding the reader")
    parser.add_argument("--public-only", action="store_true", help="Show only roots marked public")
    parser.add_argument("--due", action="store_true", help="List only the due records in detail")
    parser.add_argument("--init-config", action="store_true", help="Write a starter config and exit")
    parser.add_argument("--as-of", help="Evaluate due dates against this YYYY-MM-DD instead of today")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.init_config:
        config = discover_roots(args.parent)
        target = args.config or Path("fleet.json")
        target.write_text(json.dumps(config, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {target} with {len(config['roots'])} root(s)")
        for entry in config["roots"]:
            mark = "" if entry["declared"] else "   (no known source layout found — set sources explicitly)"
            print(f"  {entry['name']:22} {', '.join(entry['sources'])}{mark}")
        return 0

    if args.config and args.config.exists():
        config = json.loads(args.config.read_text(encoding="utf-8"))
    else:
        config = discover_roots(args.parent)

    roots = config.get("roots", [])
    if args.public_only:
        roots = [r for r in roots if r.get("visibility") == "public"]

    work = load_reader(args.skill_root)
    as_of = args.as_of or __import__("datetime").date.today().isoformat()
    scans = [scan_root(work, entry) for entry in roots]
    rows = summarise(scans, as_of)

    if args.due:
        for row in rows:
            row.pop("due_items", None)

    if args.json:
        print(json.dumps({"as_of": as_of, "public_only": args.public_only, "roots": rows,
                          "due_items": [i for r in rows for i in r.get("due_items", [])]}, indent=1))
    else:
        print_markdown(rows, as_of, args.public_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
