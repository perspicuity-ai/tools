#!/usr/bin/env python3
"""Refuse to migrate until the conditions that make it safe actually hold.

A migration has one irreversible-looking step: replacing the source tree with a pointer.
Everything before that is reversible. This preflight checks the conditions that must be
true *before* that step, and exits non-zero listing what is missing, so the run fails
closed rather than producing a repository full of links nobody can follow.

It checks, in order:

  1. the target repository does not already exist
  2. the pin names a commit that exists on the remote (a local-only SHA yields dead links)
  3. every path that will be pinned exists at that commit
  4. the source tree is clean, so the pointer commit records only the move
  5. `gh` is authenticated

Usage:
    preflight.py --root <repo> --urls <file-with-planned-urls> [--target org/name]... [--json]

Build the URL list from the rewriter:
    rewrite_cross_links.py ... --json > plan.json
    python3 -c "import json;print('\\n'.join(sorted({e['to'] for e in json.load(open('plan.json'))['edits']})))" > urls.txt
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

URL_RE = re.compile(r"https://github\.com/([^/]+/[^/]+)/blob/([0-9a-f]{7,40})/(.+?)(?:[#?].*)?$")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def repo_exists(slug):
    result = run(["gh", "repo", "view", slug, "--json", "name"])
    return result.returncode == 0, (result.stderr or "").strip()


def commit_exists(slug, sha):
    result = run(["gh", "api", f"repos/{slug}/commits/{sha}", "--jq", ".sha"])
    return result.returncode == 0, (result.stderr or "").strip()


def path_exists(slug, sha, path):
    result = run(["gh", "api", f"repos/{slug}/contents/{path}?ref={sha}", "--jq", ".type"])
    return result.returncode == 0, (result.stderr or "").strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True, help="Source repository")
    parser.add_argument("--urls", type=Path, help="File of planned URLs, one per line")
    parser.add_argument("--target", action="append", default=[], help="Repository the migration would create")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    checks, failures = [], []

    def record(name, ok, detail=""):
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            failures.append(f"{name}: {detail}")

    # 1. gh authenticated
    auth = run(["gh", "auth", "status"])
    record("gh authenticated", auth.returncode == 0,
           "" if auth.returncode == 0 else "run `gh auth login`")

    # 2. target repositories must not already exist
    for slug in args.target:
        exists, detail = repo_exists(slug)
        record(f"target absent: {slug}", not exists,
               f"{slug} already exists; the migration would collide with it" if exists else "")

    # 3. the source tree is clean, so the pointer commit is only the move
    status = run(["git", "-C", str(args.root), "status", "--porcelain"])
    tracked = [l for l in status.stdout.splitlines() if not l.startswith("??")]
    record("source tree has no uncommitted tracked changes", not tracked,
           "; ".join(tracked[:3]) if tracked else "")

    # 4. pin integrity
    if args.urls and args.urls.exists():
        targets = {}
        for line in args.urls.read_text(encoding="utf-8").splitlines():
            match = URL_RE.match(line.strip())
            if not match:
                continue
            slug, sha, path = match.groups()
            targets.setdefault((slug, sha), []).append(path)

        for (slug, sha), paths in sorted(targets.items()):
            ok, detail = commit_exists(slug, sha)
            record(f"commit exists on remote: {slug}@{sha[:8]}", ok, detail)
            if not ok:
                continue
            missing = []
            for path in sorted(set(paths)):
                present, _ = path_exists(slug, sha, path)
                if not present:
                    missing.append(path)
            record(f"all {len(set(paths))} pinned paths exist at {slug}@{sha[:8]}", not missing,
                   f"missing: {missing[:5]}" if missing else "")
    elif args.urls:
        record("urls file present", False, f"{args.urls} not found")

    if args.json:
        print(json.dumps({"ok": not failures, "checks": checks, "failures": failures}, indent=1))
    else:
        for check in checks:
            print(f"  [{'pass' if check['ok'] else 'FAIL'}] {check['check']}"
                  + (f"  -- {check['detail']}" if check["detail"] and not check["ok"] else ""))
        print(f"\npreflight: {'READY' if not failures else 'NOT READY — ' + str(len(failures)) + ' blocking'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
