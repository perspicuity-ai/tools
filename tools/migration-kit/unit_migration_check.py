#!/usr/bin/env python3
"""Verify a mirror-first unit migration before the source is replaced by a pointer.

Run this BEFORE and AFTER copying a unit tree to its own repository.

Before the copy it records an inventory of the source: byte totals, per-file digests,
and a classification of every local Markdown link into three kinds:

  internal     both ends move together, so a relative path keeps working
  cross-repo   points into the core repository; MUST be rewritten to an absolute,
               revision-pinned URL or the link dies when the tree moves
  unclassified is neither, and needs a human decision

After the copy it compares the two trees by digest and reports any missing, extra or
changed file.

This is a mechanical check. It does not establish that a rewrite target exists, that a
pinned revision is correct, or that the migrated unit is fit for use.

Usage:
    unit_migration_check.py inventory --root <repo> --unit <path> [--unit <path>] [--json]
    unit_migration_check.py compare   --root <repo> --unit <path> --mirror <path> [--json]
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# Core repository paths a unit may point into. A link starting with one of these,
# relative to the unit root, must be rewritten when the unit leaves the repository.
CORE_PREFIXES = (
    "Decisions/",
    "spec/",
    "lifecycle/",
    "graph/",
    "chain/",
    "skills/",
    "docs/design/",
    "docs/frames/",
    "docs/reviews/",
    "docs/reports/",
    "docs/plans/",
    "docs/style/",
    "publishing/",
    "release-preparation/",
    "decision-templates/",
)

TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".html", ".py"}

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#", "data:")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_contained(path, root):
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def classify_target(unit_root, repo_root, source_file, target):
    """Return (kind, resolved-or-None, note)."""
    if target.startswith(EXTERNAL_PREFIXES):
        return "external", None, "leaves the repository or is in-page"
    if Path(target).is_absolute():
        return "unclassified", None, "absolute filesystem path"
    # Strip an anchor or query before resolving.
    bare = target.split("#", 1)[0].split("?", 1)[0]
    if not bare:
        return "external", None, "anchor only"
    resolved = (source_file.parent / bare).resolve()
    if is_contained(resolved, unit_root):
        return "internal", resolved, "moves with the unit"
    if is_contained(resolved, repo_root):
        note = "MUST be rewritten to a pinned absolute URL"
        return "cross-repo", resolved, note
    return "unclassified", resolved, "resolves outside the repository"


def inventory_unit(repo_root, unit_root):
    if not unit_root.is_dir():
        raise SystemExit(f"Not a directory: {unit_root}")
    files, total_bytes, digests = [], 0, {}
    links = {"internal": 0, "cross-repo": 0, "external": 0, "unclassified": 0}
    cross_by_target, unclassified, broken_internal = {}, {}, {}
    for path in sorted(unit_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(unit_root).as_posix()
        size = path.stat().st_size
        total_bytes += size
        digests[rel] = sha256(path)
        files.append(rel)
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for match in LINK_RE.finditer(text):
            kind, resolved, note = classify_target(unit_root, repo_root, path, match.group(1))
            links[kind] += 1
            if kind == "cross-repo":
                key = match.group(1)
                entry = cross_by_target.setdefault(
                    key, {"target": key, "resolves_to": str(resolved.relative_to(repo_root)), "files": []}
                )
                entry["files"].append(rel)
            elif kind == "unclassified":
                unclassified.setdefault(match.group(1), []).append(rel)
            elif kind == "internal" and not resolved.exists():
                broken_internal.setdefault(match.group(1), []).append(rel)
    return {
        "unit": unit_root.relative_to(repo_root).as_posix(),
        "files": len(files),
        "bytes": total_bytes,
        "links": links,
        "cross_repo_targets": sorted(cross_by_target.values(), key=lambda e: -len(e["files"])),
        "unclassified_targets": {k: v for k, v in sorted(unclassified.items())},
        "broken_internal_targets": {k: v for k, v in sorted(broken_internal.items())},
        "digests": digests,
    }


def human_inventory(report):
    print(f"unit: {report['unit']}")
    print(f"files: {report['files']}   bytes: {report['bytes']:,}")
    links = report["links"]
    print(
        "links: internal {internal}  cross-repo {cross-repo}  external {external}  "
        "unclassified {unclassified}".format(**links)
    )
    cross = report["cross_repo_targets"]
    print(f"\ncross-repo link targets needing rewrite ({len(cross)}):")
    for entry in cross:
        print(f"  {entry['target']}")
        print(f"      -> {entry['resolves_to']}   in {len(entry['files'])} file(s): {entry['files'][0]}")
    if report["unclassified_targets"]:
        print("\nUNCLASSIFIED targets, each needs a decision:")
        for target, files in report["unclassified_targets"].items():
            print(f"  {target}   in {files}")
    if report["broken_internal_targets"]:
        print("\nBROKEN internal targets, already unresolvable before any move:")
        for target, files in report["broken_internal_targets"].items():
            print(f"  {target}   in {files}")
    else:
        print("\nno broken internal targets")


def compare_unit(source_root, unit_path, mirror_root):
    if not unit_path.is_dir() or not mirror_root.is_dir():
        raise SystemExit("Both the source unit and the mirror must exist")
    source = {p.relative_to(unit_path).as_posix(): p for p in unit_path.rglob("*") if p.is_file()}
    mirror = {p.relative_to(mirror_root).as_posix(): p for p in mirror_root.rglob("*") if p.is_file()}
    missing = sorted(set(source) - set(mirror))
    extra = sorted(set(mirror) - set(source))
    changed = sorted(
        rel for rel in set(source) & set(mirror) if sha256(source[rel]) != sha256(mirror[rel])
    )
    source_bytes = sum(p.stat().st_size for p in source.values())
    mirror_bytes = sum(p.stat().st_size for p in mirror.values())
    return {
        "source_files": len(source),
        "mirror_files": len(mirror),
        "source_bytes": source_bytes,
        "mirror_bytes": mirror_bytes,
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "identical": not (missing or extra or changed),
    }


def human_compare(result):
    print(f"source files {result['source_files']} ({result['source_bytes']:,} bytes)")
    print(f"mirror files {result['mirror_files']} ({result['mirror_bytes']:,} bytes)")
    if result["identical"]:
        print("\nIDENTICAL: every file matches by sha256, nothing missing or extra")
        return
    print(f"\nmissing in mirror ({len(result['missing'])}): {result['missing'][:10]}")
    print(f"extra in mirror ({len(result['extra'])}): {result['extra'][:10]}")
    print(f"changed ({len(result['changed'])}): {result['changed'][:10]}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="Inventory a unit before migration")
    inv.add_argument("--root", type=Path, required=True, help="Repository root")
    inv.add_argument("--unit", type=Path, action="append", required=True, help="Unit path, relative to root")
    inv.add_argument("--json", action="store_true")

    cmp_ = sub.add_parser("compare", help="Compare a unit against its mirror")
    cmp_.add_argument("--unit", type=Path, required=True, help="Source unit directory")
    cmp_.add_argument("--mirror", type=Path, required=True, help="Mirror directory")
    cmp_.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "inventory":
        root = args.root.resolve()
        reports = [inventory_unit(root, (root / unit).resolve()) for unit in args.unit]
        if args.json:
            print(json.dumps(reports, indent=1))
        else:
            for index, report in enumerate(reports):
                if index:
                    print()
                human_inventory(report)
        return 0

    result = compare_unit(None, args.unit.resolve(), args.mirror.resolve())
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        human_compare(result)
    return 0 if result["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
