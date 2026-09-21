# Design of the migration kit

The choices behind these seven scripts, including the ones that were measured wrong first.

This record exists because most of what makes this kit correct is a list of mistakes it was
built to stop repeating. A future reader who "simplifies" one of these choices without knowing
why will reintroduce a defect that took a real migration to find.

## The problem

Moving a directory from one git repository into its own breaks every link that crosses the new
boundary, and a broken link fails silently: nothing errors, a reader just clicks and finds
nothing. A repository is also not a tidy unit of work. One real case had three units with
different release cycles sharing one tree, where a post caption and a decision-record spec
lived in the same history.

Measured before the move: the two units being extracted were **2.6% of the repository by
size** — 13 MB and 388 KB against 505 MB. The problem was never size. It was that content
referenced the core in 8 of 71 text files while the relationship work referenced it in 19 of
21, so they were not one unit and could not sensibly share a boundary.

## Decision 1: two link directions, not one

A migration has links leaving the unit and links arriving at it from documents that stay. The
first version of this kit handled only the first. Running it against a real repository showed
**15 links across 12 documents** that would have broken at the moment the source tree was
deleted.

`rewrite_cross_links.py` handles the mirror. `outbound_links.py` handles the documents left
behind. Neither substitutes for the other, and the order matters: rewrite the arrivals before
deleting anything.

## Decision 2: internal links stay relative, cross-boundary links are pinned

The obvious approach — pin every link — is wrong, and the migration that proved it did so by
shipping the mistake into a rehearsal.

- **Internal links stay relative.** Both ends move into the same repository. Pinning them to a
  commit would freeze a live unit's internal references at migration time, so the unit could
  never link to its own newly written material without editing URLs.
- **Cross-boundary links become absolute and pinned to a commit.** A relative path cannot
  survive a move, and an unpinned URL cannot be trusted: `blob/main/...` resolves to whatever
  `main` points at when the reader clicks, so the content behind the link changes without the
  link changing.

Measured on a real unit: 233 internal links kept relative, 77 cross-boundary links pinned, 0
unresolved. After the move, a fresh clone reported 232 relative links, 0 dead, 0 escaping.

## Decision 3: rewrite the whole mirror, not the unit tree

The first rewrite pass walked only the unit's own files. A unit that takes siblings with it —
a research directory its own documents cite — arrives carrying those siblings' dead links.
The pass left **67 dead links** inside the material that was moving.

`rewrite_cross_links.py` therefore scans the assembled mirror and maps every file back to the
source it came from, so link resolution always happens against the real source location.

## Decision 4: skip fenced code blocks

A link-shaped string inside a fence is an example, not a link. Rewriting one corrupts the
example, and *counting* one overstates the work.

Both matter. In the real migration a text pattern match reported **42 link instances across 11
documents**. The true figure, counting only links outside fences that resolve to a real file,
was **15 across 12**. The overcount was nearly three times the work, and it was published in a
decision record before anyone caught it.

Rule: use a resolver, not a pattern match, for anything a reader will act on.

## Decision 5: a list of what moves, not a list of what stays

The first classifier asked "is this target part of the core?" and derived the answer from an
allow-list of core directories. Anything outside the list was assumed to be moving, which
misclassified **27 links** in a dry run and would have written 27 wrong URLs.

The correct question is "does the target move?", answered by an explicit `--moves-out` list.
Every path not listed stays. An allow-list fails open on the paths nobody thought of; a
move-list fails closed.

## Decision 6: pin to a commit that exists on the remote

Pinning to a local-only commit produces URLs that 404 for everyone else, and nothing in the
repository reveals it. This was caught by validating a rewrite against the remote before
anything was pushed.

`preflight.py` fails closed unless the target repository does not already exist, the pinned
commit exists on the remote, every pinned path resolves at that commit, the source tree has no
uncommitted tracked changes, and `gh` is authenticated.

## Decision 7: the fleet view reads the reader rather than reimplementing it

Open work lives per repository, and the project's reader deliberately searches one root and
excludes nested projects. That is right for working in a repository and useless for seeing a
portfolio, which is the problem `fleet_view.py` solves.

It calls the installed reader's `scan()` once per root instead of reimplementing what counts
as a record. The first version did reimplement one thing — the due-date filter — and compared
the prose `next_check` field as a string. That field often holds a sentence
("September 16, America/Edmonton. Connections reviews traffic when…"), so the view reported
**zero due records while the reader reported ten**. The normalised `next_check_date` field is
the one to use.

Two properties are deliberate: it never writes, so it cannot become a second store; and it
never merges private and public material into one artifact, labelling every row with its
root's visibility and offering `--public-only`.

## Decision 8: duplicates are counted once and still shown

Replacing a migrated source with a pointer can be deferred while inbound links still point at
it, so a record can legitimately exist in two roots at once. Counting it twice inflates the
queue; hiding it conceals an unfinished migration.

A root can list `exclude` prefixes. Those records leave the owner's counts and appear in a
separate "superseded" list naming where they now live. On the real migration this surfaced a
duplicate that no single-root reader could see, and after the pointer swap the superseded
count returned to zero without any config change being needed to hide it.

## Testing

`tests/test_kit.py` covers the behaviours above, including each defect that actually occurred.

The suite was checked by mutation, because a suite that cannot fail proves nothing. Disabling
fence-skipping fails exactly one test; making the rewriter pin internal links fails exactly
one test. Both mutations were reverted.

The tools also carry their own verification: `unit_migration_check.py compare` catches a
dropped file, an added file and a single appended byte; `dead_links.py` reports exactly one
dead link when one is injected into a clean tree and none in the clean tree.

## Known limits

- Link rewriting is line-based. A link whose label and target span multiple lines is not
  recognised. None were found in the migrations this was built for; a multi-line link would
  be missed rather than mangled.
- Only Markdown links in `.md` and `.txt` files are rewritten. A path written inside prose or
  a code block is left alone deliberately.
- `fleet_view.py` needs the project's reader available, either from a checkout given with
  `--skill-root` or a copy under `reader/`.
- The kit has no installer. Each script is standalone and standard-library only.
