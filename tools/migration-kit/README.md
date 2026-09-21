# Migration kit

Seven small tools for moving a directory out of one repository into its own without breaking
the links between them, and for reading open work once the split exists. Written for a real
three-way repository decomposition and reusable for any split of the same shape.

Standard library only, except `verify_pinned_targets.py`, which uses `gh` to check that every
rewritten URL resolves at the commit it names.

They are deliberately separate from the repositories they operate on, so the migration
tooling is not itself part of what is being migrated.

## Why this exists

Moving a tree between repositories breaks every link that crosses the new boundary, and a
silent link break is worse than a loud one because nothing fails until a reader clicks. The
tools below make the two questions mechanical:

1. Which links cross the boundary, and what should each become?
2. After the move, does every link still resolve?

## The tools

### `unit_migration_check.py`

Inventories a unit before migration and verifies its mirror afterwards.

```sh
python3 unit_migration_check.py inventory --root /path/to/repo --unit docs/initiatives/foo
python3 unit_migration_check.py compare --unit /path/to/repo/docs/initiatives/foo --mirror /tmp/foo
```

`inventory` reports file count, byte total, per-file digests, and every local link
classified as `internal`, `cross-repo`, `external` or `unclassified`. `compare` checks a
mirror against its source by sha256 and exits non-zero on any missing, extra or changed file.

### `rewrite_cross_links.py`

Rewrites the mirror's links. Two rules, and getting them backwards is the main way to get
this wrong:

- **Internal links stay relative.** Both ends live in the new repository, and its content is
  expected to keep changing. Pinning them would freeze a live unit at migration time.
- **Cross-boundary links become absolute and revision-pinned.** A relative path cannot
  survive a move, and an unpinned URL cannot be trusted later.

```sh
python3 rewrite_cross_links.py \
  --root /path/to/repo --unit docs/initiatives/foo --mirror /tmp/foo \
  --unit-slug org/foo-unit --core-slug org/parent --core-sha <pushed-sha> \
  --moves-out docs/research --moving-slug docs/research=org/foo-unit \
  --moved-from docs/research \
  --apply
```

Run it without `--apply` first. The whole mirror is scanned, not just the unit tree, because
a unit that takes sibling directories with it must have those rewritten too.

The source tree is never modified. Link resolution always happens against the real source
file, so the plan is computed from where things are now.

### `verify_pinned_targets.py`

Checks that every rewritten URL resolves. Reading the local checkout is not enough: the path
must exist *at the SHA recorded in the URL*.

```sh
python3 rewrite_cross_links.py ... --json | python3 -c "import json,sys;[print(e['to']) for e in json.load(sys.stdin)['edits']]" > urls.txt
python3 verify_pinned_targets.py --urls urls.txt
```

Uses `gh api`, so it needs an authenticated `gh`.

### `dead_links.py`

Reports relative links that do not resolve on the filesystem, before any move. Use it to
establish a baseline: if a link is already dead, a migration report should not be blamed for
it.

```sh
python3 dead_links.py --root /path/to/repo --path docs/outreach --path docs/initiatives/foo
```

Fenced code blocks are skipped, because a shell or text listing can contain bracket shapes
that are not links.

### `preflight.py`

Refuses to migrate until the conditions that make it safe actually hold. Run it before the
irreversible step, not after.

```sh
preflight.py --root /path/to/repo --urls planned_urls.txt --target org/new-unit
```

It fails closed unless: the target repository does not already exist, the pinned commit
exists on the remote, every pinned path resolves at that commit, the source tree has no
uncommitted tracked changes, and `gh` is authenticated. A pin to a local-only commit is the
failure this exists to catch, because it produces links that 404 for everyone else and
nothing in the repository reveals it.

### `fleet_view.py`

Reads open work across several repository roots in one view. The project's own reader is
per-root by design, which is right for working in a repository and useless for seeing the
portfolio.

```sh
fleet_view.py --config fleet.json --skill-root /path/to/perspicuity
fleet_view.py --init-config --config fleet.json     # propose a config from sibling checkouts
fleet_view.py --config fleet.json --public-only     # roots marked public only
```

It does not reimplement the reader: it loads `perspicuity_dashboard.work` and calls `scan()`
per root, so what counts as a record and what counts as due stay in one place.

Two properties worth keeping:

- **It never writes**, so it cannot become a second store.
- **It never merges private and public material into one artifact.** Every row carries its
  root's visibility, and `--public-only` filters to roots marked public.

A root that has migrated material elsewhere can list `exclude` prefixes. Those records are
left out of the owning root's counts and reported separately as superseded, so a duplicate is
counted once and still visible. This exists because replacing a migrated source with a pointer
may be deferred while inbound links still point at it.

### `outbound_links.py`

The other half of a migration. A rewriter run on the mirror fixes links leaving the unit; it
does nothing for documents that **stay behind** and now point at paths that are about to
disappear. This plans and applies those edits, and it runs on the repository being migrated
from.

```sh
outbound_links.py --root /path/to/repo --moves-out docs/outreach \
    --moving-slug docs/outreach=org/unit --sha <pushed-sha>
```

Fenced code blocks are copied through byte-identical, because a link-shaped string inside an
example is not a link. Without this tool the only way to size the job is a text pattern match,
which counts those examples and overstates the work — in one real case, 42 against a true 15.

### `split_corpus.py`

Moves domain-scoped decision records into their unit repositories, and splits a chained corpus
with them.

```sh
split_corpus.py --corpus <Decisions dir> --routing routing.json \
    --chain-tool <path to chain.py> --target content=/path --target company=/path --apply
```

**Each chain is rebuilt by calling `chain.py append`, never by hashing entries here.** The live
chain hashes an entry *including its own `sha256` field*, so a second implementation produces
links that do not verify — three attempts to reimplement it disagreed with the tool before this
was settled by direct computation. There is no reason to hold a second copy of that logic.

Two consequences it states rather than hides: new entries get new timestamps and sequence
numbers, and **signatures do not carry over**, because a signature covered a predecessor link
that no longer exists.

### `repoint_records.py`

Rewrites references to records that moved. Two forms exist and only one is a link:

```sh
repoint_records.py --root <repo> --moved moved.json --sha main [--apply]
```

A markdown link is the obvious form. A **bare identifier** in front matter — `parent:`,
`depends_on:`, `id:` — is the one that fails silently, because the record still reads as if it
resolves locally and nothing errors. Both are reported.

## Order of work

1. `dead_links.py` on the move scope, for a baseline.
2. `unit_migration_check.py inventory` on each unit.
3. Assemble the mirror by copying the unit to its new root plus whatever moves with it.
4. `rewrite_cross_links.py` without `--apply`, and read the plan.
5. `rewrite_cross_links.py --apply`.
6. `dead_links.py` against the assembled mirror: dead and escaping links must both be zero.
7. `unit_migration_check.py compare` on material that should be byte-identical.
8. `verify_pinned_targets.py` on the rewritten URLs.
9. Commit the mirror unchanged first, so the pinned SHA contains the referenced paths.
10. Only then replace the source with a pointer, in a second commit.

## Two traps

**A pin must name a commit that exists on the remote.** Pinning to a local-only commit
produces URLs that 404 for everyone else, and nothing in the repository reveals this. Check
with `git rev-list --count origin/main..HEAD` before choosing a SHA.

**Rewriting only the unit tree is not enough.** The first version of this kit did that and
left 67 dead links inside the material the unit was taking with it. The tools now scan the
whole mirror.

## Testing the tools themselves

A checker that always passes proves nothing. Both checkers were validated against deliberately
damaged copies:

- `compare` catches one file removed, one added, and one byte appended.
- `dead_links.py` reports exactly one dead link when one is injected into a clean tree, and
  zero in the clean tree.

Keep those negative controls when changing the tools. An injected failure that is not
detected is the failure mode that matters.
