# dictate — design and reasoning

This records what `dictate` does, the measurements that shaped it, and the choices
that are easy to undo by accident. Every number here was measured on the development
machine (13th Gen Intel i9-13900H, X11, ~40 ms round trip to `api.openai.com`) against
a 26-second 16 kHz mono clip, using the live API. None of them are estimates.

If you change something here, re-measure before assuming the change is neutral; the
suite in `tests/` exists so that "it still works" is a fact rather than a hope.

## What the tool is

One shell script with a toggle. First invocation starts a recorder and returns
immediately. Second invocation stops it, transcribes out of band, and inserts the text
into whatever window was focused when recording began.

The whole tool is about 440 lines, including comments. It deliberately has no daemon,
no service, no tray icon and no configuration file that must exist.

## Constraint that governs everything: it is invisible

Dictation is only useful if it is faster than typing. That gives the tool a hard
requirement that most scripts do not have: **the user must never wait on it, and must
never wonder whether it worked.**

Two consequences are worth stating, because they decide several arguments below:

- Any delay the user *feels* is a defect, even if the total work is correct.
- The tool runs attached to a global hotkey. It may be invoked twice in five seconds,
  or twice in fifty milliseconds, and it must behave sensibly both times.

## The measurement that reframed the problem

The obvious suspicion about a cloud transcription tool is that the API is slow. It is
not. Measured over repeated runs:

| Configuration | Time |
| --- | ---: |
| `gpt-4o-transcribe`, WAV, instruction prompt | 1.24 – 1.54 s |
| `gpt-transcribe`, WAV, `languages[]=en` | 1.22 – 1.43 s |
| `gpt-transcribe`, FLAC (53% smaller upload) | 1.54 s |
| `whisper-1` (reference) | 3.80 s |
| Time to first streamed token, `gpt-transcribe` | 0.96 – 1.13 s |

The API was returning a full transcript in about a second. The tool still *felt* slow.
That gap is the entire design story.

The cause was one line:

```bash
xdotool type --clearmodifiers --delay 12 -- "$TEXT"
```

`--delay 12` means 12 milliseconds of deliberate sleep per character. It exists because
fast synthetic typing drops characters in some toolkits. The cost is easy to miss in
review and large in practice:

| Transcript | Cost of the old typing path |
| --- | ---: |
| 170 characters | ~2.0 s |
| 400 characters | ~4.8 s |

So the fixed cost was about a second, and the *variable* cost — the part that scales
with how much you said — was entirely self-inflicted. Dictating a paragraph was slower
than dictating a sentence for no reason related to transcription at all.

**Lesson worth keeping:** measure the phase breakdown before optimising. Had the
perceived slowness been blamed on the model, the real bottleneck would have survived
several rounds of "improvement" to the wrong component.

## Decision 1 — Insertion is a paste, not synthetic typing

**Chosen:** put the transcript on the clipboard and send one `ctrl+v`.

**Rejected:** `xdotool type` at a lower delay.

**Reasons:** a paste is ~0.15 s regardless of transcript length, so the variable cost
disappears. It is also more faithful: `xdotool type` re-encodes the text through
keyboard events, which mangles anything that is not directly typable — accented
characters, em dashes, curly quotes. A paste transfers the actual bytes. Since
dictation routinely produces punctuation the keyboard does not have, this is a
correctness fix as much as a speed one.

**Cost accepted:** the X11 clipboard is a shared, single-slot resource. Two problems
follow, and both are handled rather than ignored:

- The user's existing clipboard is captured before insertion and restored about four
  seconds afterwards, so dictating does not destroy what they had copied.
- Because the clipboard is global, the *write* and the *keystroke* must be atomic with
  respect to other dictations. See Decision 3.

**Escape hatch:** `DICTATE_INSERT=type` restores synthetic typing, and
`DICTATE_INSERT=clipboard` only copies, for people who prefer to place the text
themselves.

### A trap that cost real debugging time

`xclip -loops 1 -i` looks like the tidy way to serve exactly one paste. It is not: with
`-loops 1` xclip stays in the foreground waiting to serve a paste request, and blocks
forever if the keystroke never lands — for example when no window has focus. Plain
`xclip -i` forks and returns immediately. This is not obvious from the flag name, so it
is called out in the script itself.

## Decision 2 — The model choice is about accuracy, not latency

**Chosen:** `gpt-transcribe`, with `languages` and optional `keywords`.

**Rejected:** staying on `gpt-4o-transcribe`; `whisper-1`.

**Reasons:** measured latency is the same across `gpt-transcribe` and
`gpt-4o-transcribe`, so speed cannot decide it. `gpt-transcribe` is the vendor's current
recommendation for recorded speech, and — the part that matters for a dictation tool —
it accepts a `keywords` list. Dictation into a specialist context constantly fails on
names, acronyms and jargon; keywords are the mechanism for fixing exactly that, and
`gpt-4o-transcribe` has no equivalent.

`whisper-1` is three times slower and exists here only as a reference point. It is kept
reachable because it is the only model that returns word timestamps, which a future
feature might want.

**Rejected on principle:** the old script passed an *instruction* as the prompt —
"Transcribe all speech completely, including any trailing sentences." Transcription
prompts are context, not commands. An instruction-shaped prompt does not steer the
model; at best it does nothing and at worst it invites the model to generate text to
satisfy the instruction. The prompt is now used for what it is for: vocabulary and
domain context, drawn from a file the user controls.

**Also rejected, with a measurement:** a second pass through a chat model to clean up
filler words and punctuation. It costs 0.8 – 1.3 s, which is roughly the entire
transcription budget, to fix something the user can read past. If it is ever added it
should run *after* the raw text is inserted and replace it in place, so the user never
waits for polish.

### A limitation found by testing rather than reading

`gpt-4o-transcribe` silently ignores `stream=true` — zero events are returned. Only
`gpt-transcribe` streams. Streaming buys ~250 ms on a one-second response, which is
real but small, and it cannot be used here anyway: the audio is not available until the
user stops recording, so there is no earlier point at which to start uploading. The
tool therefore does not stream, and that is a considered choice rather than an omission.

## Decision 3 — Transcription happens out of band, and insertion is serialised

This is the most subtle part of the design and the part most likely to be "simplified"
into a regression.

**Chosen:** the second hotkey press does the minimum work — stop the recorder, validate
the file, hand off to a detached worker — and returns. The worker transcribes and
inserts.

**Reason:** the user should be able to start the next utterance immediately. The
original script instead set a busy flag and refused further input until transcription
finished, which meant the API's one second became a visible lockout. Removing that
lockout was as valuable as making insertion fast.

The cost is concurrency, and concurrency here is genuinely dangerous because insertion
goes through a single global clipboard. Two workers inserting at once can interleave
such that the application pastes worker A's keystroke with worker B's clipboard
contents — the wrong text, silently.

**The fix is narrow and deliberate:** the clipboard write *and* the `ctrl+v` keystroke
happen together while holding one lock; clipboard restore is scheduled under the same
lock. That is the only region that must be atomic.

### An approach that was tried and abandoned

The first attempt tried to force insertion into *recording order*, using the sequence
number to make a later utterance wait for an earlier one. That is wrong in principle,
not merely buggy: if utterance 2 is ready first, blocking it does not make utterance 1
readier — it just loses utterance 2's text. Testing two concurrent utterances showed
exactly that, with one transcript silently vanishing.

Insertion order is now completion order. For real use — utterances seconds apart,
transcription faster than it takes to speak the next sentence — completion order *is*
recording order. Where it is not, the user gets both transcripts, correctly separated,
in the wrong order, which is a far better failure than losing one.

**This is the single most important thing to preserve in this file.** Re-introducing
ordering looks like a correctness improvement and is actually a data-loss bug.

## Decision 4 — State is ephemeral, named, and self-healing

State lives under `${XDG_RUNTIME_DIR}/dictate`: the recorder's PID and audio path, the
paste lock, and a sequence counter. It is deliberately not durable, because every piece
of it describes something that is either running right now or already lost.

Three failure modes were found by testing, and each is handled:

- **A stale lock file.** If the script is killed between starting the recorder and the
  second press, a lock file survives with a dead PID. The stop path tolerates a missing
  recorder and reports rather than proceeding to transcribe nothing.
- **An unwritable `XDG_RUNTIME_DIR`.** The directory is the correct home for this state,
  but it is not always writable — restricted sandboxes and unusual session setups both
  break it. Failing there is silent and total: the script produces nothing at all. It
  now falls back to a private directory under `TMPDIR` and re-points every derived path.
- **A recorder that outlives its parent.** `rec` inherits the caller's stdio by default,
  so `dictate | anything` never returns; the pipe stays open as long as the recorder
  lives. The recorder is now started under `setsid` with its stdio redirected. Measured:
  the piped invocation returns in 266 ms instead of hanging until the timeout.

### The file-descriptor trap

Worth recording because it is invisible in review and produced a 10-second stall.

`xclip` forks a daemon to own the clipboard selection and can live for as long as the
text is on the clipboard. Because insertion holds the paste lock on file descriptor 9,
that daemon **inherits the descriptor and keeps the lock held** for its entire lifetime.
The next dictation then blocks on a lock whose owner is a clipboard process that has
nothing to do with it.

Any code holding this lock that spawns a long-lived child must close descriptors 3–9
first. There is a helper for this, and a comment where it is used. Removing the helper
reintroduces a stall that looks like an API problem and is not.

## Decision 5 — Configuration over code, but no configuration required

The tool works with one environment variable (`OPENAI_API_KEY`) and nothing else.
Everything beyond that is optional and layered, with one rule: **the real environment
beats the files.** A one-off `DICTATE_MODEL=whisper-1 dictate` must always work, which
is why the defaults are resolved after the files are read.

| File | Purpose |
| --- | --- |
| `~/.config/dictate/env` | The API key. Existing users had this; it stays authoritative. |
| `~/.config/dictate/keywords.txt` | Domain vocabulary. **The main accuracy lever.** |
| `~/.config/dictate/context.txt` | One or two sentences of domain context. |
| `~/.config/dictate/options.conf` | Optional setting defaults, so `env` can stay minimal. |

Keywords deserve emphasis. The gap between this tool and a polished commercial
dictation product is mostly vocabulary: it does not yet know your colleagues' names,
your project names, or your acronyms. `keywords.txt` is where that is fixed, and it is a
file rather than a code change on purpose.

## What was deliberately not built

Recording these prevents them being re-litigated from scratch:

- **Local transcription.** Whisper models run locally and would remove the per-use cost
  and the network dependency. Not built: the development machine has no working NVIDIA
  driver, so this would be CPU-only, and the measured API latency is already below the
  threshold where a local model would win on speed. Worth revisiting if a GPU appears or
  if volume makes cost matter.
- **Streaming insertion.** Type text as it streams in, rather than pasting at the end.
  Saves ~250 ms and can interleave with whatever the user types during the gap. Rejected
  as a bad trade.
- **Cleanup pass.** See Decision 2.
- **A daemon.** The tool is invoked by a hotkey a few times an hour. A daemon would add
  a supervision problem, a startup-order problem and a way to leak a microphone, to save
  a process spawn.

## Verification

`tests/suite.sh` runs five scenarios against the live API with no microphone required,
by synthesising the recording and driving the real code paths:

1. syntax, and that sourcing the file for the detached worker has no side effects
2. one utterance end to end: real API call, paste into a real window, clipboard restored
3. two concurrent utterances: both transcripts must arrive intact
4. an invalid API key: must exit non-zero and log the failure
5. `xclip` absent: must fall back to typing

It exists because the interesting failures here are all concurrency and resource
failures that only appear under load and are invisible in review. Scenario 3 in
particular is a regression test for the abandoned ordering design.

## Costs and privacy

Every dictation sends audio of the user's voice to OpenAI. That is inherent to the
design, not incidental: it is a cloud transcription tool. The audio file is written to
the state directory during recording and deleted after upload; a copy is kept at
`/tmp/dictate-last.*` for debugging, which is worth knowing if the tool is used for
anything sensitive.

The tool is otherwise free to run apart from API usage, which is charged per audio
token. A first-generation script with no tests, no vendor dependency and no network call
is a real alternative for anyone who does not want that trade.
