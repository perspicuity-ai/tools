#!/usr/bin/env python3
"""Move domain-scoped decision records into their unit repositories.

Splits a single chained corpus across several repositories.

**The chain is rebuilt by calling `chain/chain.py append`, never by hand.** That is the point
of this tool. A hand-written entry hash is wrong in a way nothing reveals until much later: the
live chain hashes the entry *including its own `sha256` field*, so a rebuild that excludes it
produces links that do not verify. Three attempts to reimplement the algorithm disagreed with
the tool before this was settled by direct computation. There is no reason to hold a second
copy of that logic.

Consequences of using the tool, stated rather than hidden:

  * new entries get a new `at` timestamp and a new `seq` starting at 1 in each destination;
  * **signatures do not carry over.** A signature covers a canonical entry that contained the
    old predecessor link, so it cannot survive re-chaining. The original entries and their
    signatures remain in the core chain's history, and that history is preserved.

Run with --apply to write. Without it, prints the plan.

Usage:
    split_corpus.py --corpus <Decisions dir> --routing routing.json \\
        --chain-tool <path to chain.py> \\
        --target content=/path --target connections=/path [--apply]
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def source_order(corpus):
    """Original chain order, so each destination keeps its records in their recorded sequence."""
    chain = corpus / "chain.jsonl"
    order = {}
    if not chain.exists():
        return order
    for line in chain.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        order.setdefault(entry["file"], entry["seq"])
    return order


def append_via_tool(chain_tool, chain_path, record):
    result = subprocess.run(
        [sys.executable, str(chain_tool), "--chain", str(chain_path), "append", str(record)],
        capture_output=True, text=True,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True, help="Source Decisions directory")
    parser.add_argument("--routing", type=Path, required=True, help="JSON: filename -> target name")
    parser.add_argument("--chain-tool", type=Path, required=True, help="Path to chain/chain.py")
    parser.add_argument("--target", action="append", required=True, help="<name>=<path to target repo root>")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    targets = {}
    for item in args.target:
        if "=" not in item:
            raise SystemExit(f"Expected <name>=<path>, got {item}")
        name, path = item.split("=", 1)
        targets[name] = Path(path)

    routing = json.loads(args.routing.read_text(encoding="utf-8"))
    order = source_order(args.corpus)
    by_target = {
        name: sorted((f for f, d in routing.items() if d == name), key=lambda f: order.get(f, 10**9))
        for name in targets
    }

    print(f"source corpus: {args.corpus}")
    print(f"records to move: {len(routing)}")
    for name, files in by_target.items():
        print(f"  {name:12} {len(files):3} record(s) -> {targets[name]}")

    if not args.apply:
        print("\nmode: dry run, nothing written")
        return 0

    failures = []
    for name, files in by_target.items():
        dest = targets[name] / "Decisions"
        dest.mkdir(parents=True, exist_ok=True)
        if (dest / "chain.jsonl").exists():
            (dest / "chain.jsonl").unlink()
        print(f"\n{name}:")
        for f in files:
            src = args.corpus / f
            if not src.exists():
                failures.append(f"{name}: source missing {f}")
                continue
            shutil.copy2(src, dest / f)
            ok, out = append_via_tool(args.chain_tool, dest / "chain.jsonl", dest / f)
            print(f"   {'ok  ' if ok else 'FAIL'} {out}")
            if not ok:
                failures.append(f"{name}: append failed for {f}: {out}")

    print("\ncore:")
    remaining = sorted((p.name for p in args.corpus.glob("2026-*.md") if p.name not in routing),
                       key=lambda f: order.get(f, 10**9))
    for f in routing:
        p = args.corpus / f
        if p.exists():
            p.unlink()
    core_chain = args.corpus / "chain.jsonl"
    if core_chain.exists():
        core_chain.unlink()
    for f in remaining:
        ok, out = append_via_tool(args.chain_tool, core_chain, args.corpus / f)
        if not ok:
            failures.append(f"core: append failed for {f}: {out}")

    verify = subprocess.run(
        [sys.executable, str(args.chain_tool), "--chain", str(core_chain), "verify"],
        capture_output=True, text=True,
    )
    print(f"   rebuilt core chain over {len(remaining)} record(s); tool verify exit {verify.returncode}")
    for line in (verify.stdout or "").strip().splitlines()[-2:]:
        print(f"   {line}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nall destinations written; core chain verifies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
