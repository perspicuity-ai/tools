# Tools

Small, tested command-line tools from [Perspicuity AI](https://github.com/perspicuity-ai).

Each tool is self-contained, lives in its own directory, and carries the reasoning
behind its design. These are not demos. They are used daily, and the tests in each
directory are the ones that actually run against the installed tool.

## The tools

| Tool | What it does | Needs |
|---|---|---|
| [`dictate`](tools/dictate/) | Toggle voice dictation. Press a hotkey, speak, press it again: the words are transcribed and inserted into the focused window. | Linux/X11, an OpenAI API key |

## Shape of a tool

Copy the one that is here:

```
tools/<name>/
  README.md          what it does, how to install it, what it costs to run
  <name>             the tool itself
  docs/DESIGN.md     the choices behind it, with the measurements that decided them
  tests/             a suite that runs without special hardware
```

`docs/DESIGN.md` is the part that matters. A tool here should record *why* it works
the way it does, including the measurement that ruled out the obvious alternative.
That is what stops the next person from "simplifying" a deliberate choice back into
a bug.

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
