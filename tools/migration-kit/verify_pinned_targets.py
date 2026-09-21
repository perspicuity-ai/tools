#!/usr/bin/env python3
"""Verify that every rewritten revision-pinned URL resolves to a real file.

A rewrite is only correct if the target exists at the pinned commit. This checks each
unique target path once with `gh api repos/<slug>/contents/<path>?ref=<sha>`, so 117 links
cost far fewer requests than 117.

Reading the current checkout is not enough: the paths must exist at the SHA recorded in
the URL, which is the whole point of pinning.

Usage:
    verify_pinned_targets.py --urls urls.txt [--urls-from-stdin] [--json]

Input is one URL or "repo-relative-path<TAB>owner-slug" per line, or URLs alone.
"""

import argparse
import json
import re
import subprocess
import sys

URL_RE = re.compile(r"https://github\.com/([^/]+/[^/]+)/blob/([0-9a-f]{7,40})/(.+?)(?:[#?].*)?$")


def gh_file_exists(slug, sha, path):
    result = subprocess.run(
        ["gh", "api", f"repos/{slug}/contents/{path}?ref={sha}", "--jq", ".type"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True, result.stdout.strip()
    message = (result.stderr or "").strip().splitlines()
    return False, message[-1] if message else f"exit {result.returncode}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--urls", type=argparse.FileType("r"), default=sys.stdin)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    targets, unparsed = {}, []
    for line in args.urls:
        line = line.strip()
        if not line:
            continue
        match = URL_RE.match(line)
        if not match:
            unparsed.append(line)
            continue
        slug, sha, path = match.groups()
        targets.setdefault((slug, sha, path), 0)
        targets[(slug, sha, path)] += 1

    results, failures = [], []
    for (slug, sha, path), count in sorted(targets.items()):
        ok, detail = gh_file_exists(slug, sha, path)
        entry = {"slug": slug, "sha": sha, "path": path, "links": count, "ok": ok, "detail": detail}
        results.append(entry)
        if not ok:
            failures.append(entry)

    if args.json:
        print(json.dumps({"checked": len(results), "failures": failures, "unparsed": unparsed}, indent=1))
    else:
        print(f"unique pinned targets checked: {len(results)} (covering {sum(t for t in targets.values())} links)")
        print(f"resolved: {len(results) - len(failures)}   failed: {len(failures)}")
        for entry in failures:
            print(f"  FAIL {entry['slug']} @ {entry['sha'][:8]}  {entry['path']}\n       {entry['detail']}")
        if unparsed:
            print(f"\nunparsed lines: {unparsed}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
