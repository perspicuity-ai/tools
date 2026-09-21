#!/usr/bin/env python3
"""Point documents that stay behind at material that moved to another repository.

Migration has two link directions and a mirror rewriter only handles one. Running a rewriter
on the copy fixes links leaving the unit; it does nothing for the documents that stay, which
now point at paths that are about to disappear. In one real migration that was 42 link
instances across 11 documents, and every one would have broken at the moment the source tree
was replaced.

This tool plans and applies those edits. It runs on the repository being migrated FROM, and
it is the step that must happen before a source directory is deleted.

A link is rewritten only when it resolves inside a path listed in --moves-out. Everything
else is left alone, including links between two moving paths, because those keep working
relative to each other once both are in the new repository.

Fenced code blocks are left byte-identical. A link-shaped string inside a code block is not a
link, and rewriting one would corrupt the example.

Usage:
    outbound_links.py --root <repo> --moves-out docs/research \
        --moving-slug docs/research=org/unit --sha <sha> [--apply] [--json]

Without --apply nothing is written and the plan is printed. Read the plan before applying: it
names every document whose content would change.
"""

import argparse
import json
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt"}
LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^)\s#?]+)((?:[#?][^)\s]*)?\))")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "data:")
FENCE_RE = re.compile(r"^(\s*)(```|~~~)")

_APPLY = False


def is_contained(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def owning_slug(rel_posix, moving_slugs):
    """Longest matching prefix wins, so a nested path can override its parent."""
    best, best_len = None, -1
    for prefix, slug in moving_slugs.items():
        if rel_posix == prefix or rel_posix.startswith(prefix.rstrip("/") + "/"):
            if len(prefix) > best_len:
                best, best_len = slug, len(prefix)
    return best


def is_moving(rel_posix, moving):
    return any(rel_posix == p or rel_posix.startswith(p.rstrip("/") + "/") for p in moving)


def rewrite_text(text, rel, base_dir, repo_root, moves_out, moving_slugs, sha, counts, edits, errors):
    """Return (new_text, changed). Fenced blocks are copied through untouched."""
    out, inside, changed = [], False, False
    for line in text.splitlines(keepends=True):
        if FENCE_RE.match(line):
            inside = not inside
            out.append(line)
            continue
        if inside:
            out.append(line)
            continue

        def replace(match):
            nonlocal changed
            prefix, target, suffix = match.group(1), match.group(2), match.group(3)
            if target.startswith(EXTERNAL_PREFIXES) or Path(target).is_absolute():
                counts["unchanged"] += 1
                return match.group(0)

            resolved = (base_dir / target).resolve()
            if not is_contained(resolved, repo_root):
                counts["unchanged"] += 1
                return match.group(0)

            target_rel = resolved.relative_to(repo_root).as_posix()
            if not is_moving(target_rel, moves_out):
                counts["unchanged"] += 1
                return match.group(0)

            # If the linking document also moves and keeps its shape, the relative link
            # survives the move untouched.
            if is_moving(rel, moves_out):
                counts["skipped_moving"] += 1
                return match.group(0)

            slug = owning_slug(target_rel, moving_slugs)
            if not slug:
                counts["unresolved"] += 1
                errors.append(
                    f"{rel}: {target} moves out of this repository but no slug was supplied "
                    f"for {target_rel}; pass --moving-slug <path>=<org/name>"
                )
                return match.group(0)

            anchor = suffix if suffix.startswith("#") else ""
            url = f"https://github.com/{slug}/blob/{sha}/{target_rel}{anchor}"
            counts["rewritten"] += 1
            changed = True
            edits.append({"file": rel, "from": target, "to": url, "now_in": slug})
            return prefix + url + suffix

        out.append(LINK_RE.sub(replace, line))
    return "".join(out), changed


def main(argv=None):
    global _APPLY
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="Repository being migrated from")
    parser.add_argument("--moves-out", action="append", required=True,
                        help="Repo-relative path that leaves this repository; repeatable")
    parser.add_argument("--moving-slug", action="append", required=True,
                        help="<repo-relative path>=<org/name> for a moving path")
    parser.add_argument("--sha", required=True, help="Pushed commit to pin to")
    parser.add_argument("--skip", action="append", default=[],
                        help="Repo-relative path to leave alone; repeatable")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    _APPLY = args.apply

    moving_slugs = {}
    for item in args.moving_slug:
        if "=" not in item:
            raise SystemExit(f"Expected <path>=<org/name>, got {item}")
        path, slug = item.split("=", 1)
        moving_slugs[path] = slug

    repo_root = args.root.resolve()
    edits, errors = [], []
    counts = {"unchanged": 0, "rewritten": 0, "skipped_moving": 0, "unresolved": 0}
    files = []

    for path in sorted(repo_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if "__pycache__" in path.parts or ".git" in path.parts:
            continue
        rel = path.relative_to(repo_root).as_posix()
        if is_moving(rel, args.skip):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue

        new_text, changed = rewrite_text(text, rel, path.parent, repo_root, args.moves_out,
                                         moving_slugs, args.sha, counts, edits, errors)
        if changed:
            files.append(rel)
            if _APPLY:
                path.write_text(new_text, encoding="utf-8")

    if args.json:
        print(json.dumps({"counts": counts, "files": sorted(files), "edits": edits,
                          "errors": errors, "applied": args.apply}, indent=1))
        return 1 if errors else 0

    print(f"link classes: {counts}")
    print(f"documents changed: {len(files)}   links rewritten: {len(edits)}")
    for name in sorted(files):
        n = sum(1 for e in edits if e["file"] == name)
        print(f"  {name}  ({n} link{'s' if n != 1 else ''})")
    if errors:
        print(f"\nUNRESOLVED ({len(errors)}):")
        for error in errors[:10]:
            print(f"  {error}")
    print(f"\nmode: {'APPLIED' if args.apply else 'dry run, nothing written'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
