#!/usr/bin/env python3
"""Rewrite a unit's cross-repository links to revision-pinned absolute URLs.

Run this on the MIRROR after assembling it and before committing it into its own
repository. Relative links that stay inside the new repository are left alone, because a
tree moved with its shape preserved keeps every internal relative path working.

The mirror is processed as a whole, not just the unit tree. A unit that takes siblings
with it -- for example a research directory its own documents cite -- must have those
siblings rewritten too, or they arrive carrying dead relative links. An earlier version
walked only the unit tree and left 67 broken links in a dry run; processing the mirror is
the correction.

Every file in the mirror is mapped back to the source it was copied from, so link
resolution always happens against the real source location:

  path under the unit prefix   ->  the same path under the unit's source root
  path listed in --moved-from  ->  the same path under the repository root

The question that decides a link's fate is "does the target move?", not "is the target
part of the core?". --moves-out states that explicitly; every other path stays put.

  target inside the new repo   left untouched
  target staying behind        rewritten to --core-slug, pinned to --core-sha
  target moving, slug known    rewritten to that slug, pinned to --core-sha
  target moving, slug unknown  reported, never guessed at
  external or anchor-only      left untouched
  absolute filesystem path     reported, unless it points inside the repository, in which
                               case it is rewritten as a staying target

Pinning requires a commit SHA that already exists on the remote. Use the two-commit order:
commit the untouched mirror first, pin to that pushed SHA, then let the link rewrites and
the source-pointer removal land in a second commit. Pinning to a local-only commit
produces links that 404.

Usage:
    rewrite_cross_links.py --root <repo> --unit <unit-path> --mirror <dir> \
        --unit-slug org/name --core-slug org/name --core-sha <pushed-sha> \
        --moves-out docs/research --moving-slug docs/research=org/name \
        [--moved-from docs/research] [--apply] [--json]

Without --apply nothing is written and the plan is printed.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".html", ".py"}

LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^)\s#?]+)((?:[#?][^)\s]*)?\))")

EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:")

_APPLY = False
_UNIT_SLUG = ""


def is_contained(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def url_for(slug, sha, path_in_repo, anchor):
    return f"https://github.com/{slug}/blob/{sha}/{path_in_repo}{anchor}"


def owning_slug(rel_posix, moving_slugs):
    """Longest matching prefix wins, so a nested path can override its parent."""
    best, best_len = None, -1
    for prefix, slug in moving_slugs.items():
        if rel_posix == prefix or rel_posix.startswith(prefix.rstrip("/") + "/"):
            if len(prefix) > best_len:
                best, best_len = slug, len(prefix)
    return best


def source_for(mirror_file, mirror_root, moved_from, repo_root, unit_root):
    """Map a file in the mirror back to the source file it was copied from."""
    rel = mirror_file.relative_to(mirror_root).as_posix()
    for moved in sorted(moved_from, key=len, reverse=True):
        if rel == moved or rel.startswith(moved.rstrip("/") + "/"):
            return repo_root / rel
    return unit_root / rel


def plan_rewrites(repo_root, unit_root, mirror_root, core_slug, core_sha,
                  moves_out, moving_slugs, moved_from):
    repo_root, unit_root, mirror_root = (Path(p).resolve() for p in (repo_root, unit_root, mirror_root))
    unit_prefix = unit_root.relative_to(repo_root).as_posix()
    edits, errors, dead = [], [], []
    counts = {"internal": 0, "external": 0, "rewritten": 0, "dead_relative": 0, "unresolved": 0}
    scanned = 0

    for mirror_file in sorted(mirror_root.rglob("*")):
        if not mirror_file.is_file() or mirror_file.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if "__pycache__" in mirror_file.parts:
            continue
        scanned += 1
        source_file = source_for(mirror_file, mirror_root, moved_from, repo_root, unit_root)
        rel = (source_file.relative_to(repo_root).as_posix()
               if is_contained(source_file, repo_root) else mirror_file.name)

        try:
            text = source_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            try:
                text = mirror_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue

        state = {"changed": False}

        def replace(match):
            prefix, target, suffix = match.group(1), match.group(2), match.group(3)
            anchor = suffix if suffix.startswith("#") else ""

            if target.startswith(EXTERNAL_PREFIXES):
                counts["external"] += 1
                return match.group(0)

            if Path(target).is_absolute():
                if is_contained(target, repo_root):
                    target_rel = Path(target).resolve().relative_to(repo_root).as_posix()
                    url = url_for(core_slug, core_sha, target_rel, anchor)
                    counts["rewritten"] += 1
                    state["changed"] = True
                    edits.append({"file": rel, "from": target, "to": url, "repo": core_slug,
                                  "reason": "absolute path inside the repository"})
                    return prefix + url + suffix
                counts["unresolved"] += 1
                errors.append(f"{rel}: absolute filesystem path outside the repository: {target}")
                return match.group(0)

            resolved = (source_file.parent / target).resolve()
            if not is_contained(resolved, repo_root):
                counts["unresolved"] += 1
                errors.append(f"{rel}: resolves outside the repository: {target}")
                return match.group(0)

            target_rel = resolved.relative_to(repo_root).as_posix()
            in_unit = target_rel == unit_prefix or target_rel.startswith(unit_prefix + "/")
            target_moved_with_unit = any(
                target_rel == moved or target_rel.startswith(moved.rstrip("/") + "/")
                for moved in moved_from
            )
            staying = not any(
                target_rel == path or target_rel.startswith(path.rstrip("/") + "/")
                for path in moves_out
            )

            if in_unit or target_moved_with_unit:
                # Both ends live in the new repository, so keep the link relative. Pinning a
                # repository's own internal links to a commit would freeze them at migration
                # time, and the unit's content is expected to keep changing afterwards.
                target_in_new_repo = target_rel[len(unit_prefix) + 1:] if in_unit else target_rel
                dest_dir = mirror_file.parent.relative_to(mirror_root).as_posix()
                relative = Path(os.path.relpath(target_in_new_repo, start=dest_dir)).as_posix()
                counts["internal"] += 1
                if relative != target:
                    state["changed"] = True
                    edits.append({"file": rel, "from": target, "to": relative, "repo": _UNIT_SLUG,
                                  "reason": "internal relative link re-based"})
                return prefix + relative + suffix
            if staying:
                url, owner = url_for(core_slug, core_sha, target_rel, anchor), core_slug
            else:
                slug = owning_slug(target_rel, moving_slugs)
                if not slug:
                    counts["unresolved"] += 1
                    errors.append(
                        f"{rel}: {target} moves out of the repository but no slug was supplied "
                        f"for {target_rel}; pass --moving-slug <path>=<org/name>"
                    )
                    return match.group(0)
                url, owner = url_for(slug, core_sha, target_rel, anchor), slug

            if not resolved.exists():
                counts["dead_relative"] += 1
                dead.append({"file": rel, "target": target, "resolved": str(resolved)})

            counts["rewritten"] += 1
            state["changed"] = True
            edits.append({"file": rel, "from": target, "to": url, "repo": owner})
            return prefix + url + suffix

        new_text = LINK_RE.sub(replace, text)
        if state["changed"] and _APPLY:
            mirror_file.write_text(new_text, encoding="utf-8")

    return edits, errors, dead, counts, scanned


def main(argv=None):
    global _APPLY, _UNIT_SLUG
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="Repository root being migrated from")
    parser.add_argument("--unit", type=Path, required=True, help="Unit path inside that root")
    parser.add_argument("--mirror", type=Path, required=True, help="Assembled mirror to rewrite")
    parser.add_argument("--unit-slug", required=True, help="org/name of the unit's new repository")
    parser.add_argument("--core-slug", required=True, help="org/name of the repository that keeps the rest")
    parser.add_argument("--core-sha", required=True, help="Pushed commit SHA containing the referenced paths")
    parser.add_argument("--moves-out", action="append", default=[],
                        help="Repo-relative path that leaves this repository; repeatable")
    parser.add_argument("--moving-slug", action="append", default=[],
                        help="<repo-relative path>=<org/name> for a moving path")
    parser.add_argument("--moved-from", action="append", default=[],
                        help="Repo-relative path copied into the mirror at the same relative location")
    parser.add_argument("--apply", action="store_true", help="Write the rewrites into the mirror")
    parser.add_argument("--json", action="store_true", help="Emit the full plan as JSON")
    args = parser.parse_args(argv)
    _APPLY = args.apply
    _UNIT_SLUG = args.unit_slug

    moving_slugs = {}
    for item in args.moving_slug:
        if "=" not in item:
            raise SystemExit(f"Expected <path>=<org/name>, got {item}")
        path, slug = item.split("=", 1)
        moving_slugs[path] = slug

    edits, errors, dead, counts, scanned = plan_rewrites(
        args.root, args.root / args.unit, args.mirror, args.core_slug, args.core_sha,
        args.moves_out, moving_slugs, args.moved_from,
    )

    files = sorted({e["file"] for e in edits})
    if args.json:
        print(json.dumps({"counts": counts, "files_scanned": scanned, "files_rewritten": files,
                          "edits": edits, "errors": errors, "dead_relative": dead,
                          "applied": args.apply}, indent=1))
        return 1 if errors else 0

    print(f"files scanned: {scanned}   link classes: {counts}")
    print(f"files needing rewrite: {len(files)}   links to rewrite: {len(edits)}")
    by_repo = {}
    for edit in edits:
        by_repo[edit["repo"]] = by_repo.get(edit["repo"], 0) + 1
    for slug, count in sorted(by_repo.items()):
        print(f"  -> {slug}: {count}")
    if dead:
        print(f"\nALREADY-DEAD relative links, unresolvable in the source tree ({len(dead)}):")
        for entry in dead[:10]:
            print(f"  {entry['file']} -> {entry['target']}")
    if errors:
        print(f"\nUNRESOLVED, needs a decision ({len(errors)}):")
        for error in errors[:10]:
            print(f"  {error}")
    print(f"\nmode: {'APPLIED' if args.apply else 'dry run, nothing written'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
