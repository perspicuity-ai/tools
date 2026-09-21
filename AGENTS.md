# Tools — agent instructions

Read [README.md](README.md). This repository holds small, tested command-line tools, each
self-contained in its own directory.

## The standard an entry meets

```
tools/<name>/
  README.md          what it does, how to install it, what it costs to run
  <name>             the tool itself
  docs/DESIGN.md     the choices behind it, with the measurements that decided them
  tests/             a suite that runs without special hardware
```

`docs/DESIGN.md` is the part that matters. A tool here records *why* it works the way it does,
including the measurement that ruled out the obvious alternative. That is what stops the next
person from "simplifying" a deliberate choice back into a bug.

## This repository is public

Anything committed here is visible to strangers and read as a claim about how the organisation
works.

- **No credentials, tokens, machine-local paths, or private repository names.** Copy the
  `dictate` or `migration-kit` entry as the shape to follow, then check for these before
  committing.
- **No private data in examples.** A usage example that names a real account, client or private
  repository is a disclosure. Generalise it.
- **State limits.** A tool that has a known failure mode documents it rather than implying it
  has none.

## Tests must be able to fail

A suite that always passes proves nothing. When adding or changing a tool, confirm the test
fails when the behaviour it covers is deliberately broken. `migration-kit` records this
practice and two mutations that were used to check it.

## Licence

Apache 2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). New entries inherit it.
