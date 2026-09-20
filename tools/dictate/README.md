# dictate

Toggle voice dictation for Linux/X11. Press a hotkey, speak, press it again — the words
are transcribed and inserted into whatever window was focused when you started.

It is about a second from the second keypress to text on screen, and it does not block
you from starting the next sentence while the previous one is still transcribing.

## Requirements

- Linux with X11 (`xdotool` and `xclip` are X11 tools; Wayland is not supported)
- `sox`, `curl`, `jq`, `xdotool`, `xclip`, `notify-send`
- An OpenAI API key with access to the transcription API

## Install

```bash
git clone https://github.com/perspicuity-ai/tools.git
cd tools/tools/dictate
./install.sh
```

`install.sh` copies the script to `~/.local/bin/dictate` and writes starter
configuration. It will not overwrite an existing API key file.

Then store your key and bind a hotkey:

```bash
mkdir -p ~/.config/dictate
printf 'OPENAI_API_KEY=sk-...\n' > ~/.config/dictate/env
chmod 600 ~/.config/dictate/env
```

For GNOME, a custom shortcut running `dictate` works; bind it to something you can reach
without looking, such as `Super+D`. Any desktop environment with global hotkeys will do.

## Use

| Action | What happens |
| --- | --- |
| Press the hotkey | Recording starts. A notification confirms it. |
| Press it again | Recording stops, transcription runs in the background, the text is pasted into the focused window. |
| Press it again immediately | The next recording starts at once. The previous transcription finishes on its own. |

The text arrives by clipboard paste, so it lands in any application that accepts
`ctrl+v`. **In a terminal, set `DICTATE_PASTE_KEY=ctrl+shift+v`** — terminals do not use
plain `ctrl+v`.

Your own clipboard is preserved: it is captured before insertion and restored a few
seconds afterwards.

## Make it accurate for your vocabulary

The single biggest improvement available is telling the transcriber what words to expect.
Edit `~/.config/dictate/keywords.txt`, one literal term per line:

```
Janus
BibTeX
LaTeX
Nelson-Elske
```

Use it for names, acronyms, product names and jargon — things a general model would
plausibly mishear. Keep the list short and relevant; these are hints, and irrelevant
entries can leak into the output.

`~/.config/dictate/context.txt` takes one or two sentences of domain context, which
helps with punctuation and register.

## Configuration

Every setting is an environment variable, so a one-off override is just a prefix:

```bash
DICTATE_MODEL=whisper-1 dictate
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `DICTATE_MODEL` | `gpt-transcribe` | Transcription model. `gpt-4o-transcribe` and `whisper-1` also work. |
| `DICTATE_LANGUAGES` | `en` | Expected input language(s). |
| `DICTATE_INSERT` | `paste` | `paste`, `type` (synthetic typing) or `clipboard` (copy only). |
| `DICTATE_PASTE_KEY` | `ctrl+v` | Paste keystroke. Use `ctrl+shift+v` in terminals. |
| `DICTATE_KEEP_CLIPBOARD` | `0` | `1` leaves the transcript on the clipboard instead of restoring yours. |
| `DICTATE_ENCODER` | `flac` | Upload format: `flac`, `wav` or `mp3`. |
| `DICTATE_PAD` | `0` | `1` appends trailing silence. Off: it changed nothing measurable. |
| `DICTATE_MIN_DURATION` | `0.5` | Recordings shorter than this are discarded, in seconds. |
| `DICTATE_API_TIMEOUT` | `60` | Request timeout, in seconds. |
| `DICTATE_API_RETRIES` | `1` | Retries after a failed request. |
| `DICTATE_TYPE_DELAY` | `2` | Per-character delay, `DICTATE_INSERT=type` only. |
| `DICTATE_NOTIFY` | `1` | `0` disables desktop notifications. |
| `DICTATE_TIMING_LOG` | state dir | Where phase timings are appended. |

Put persistent overrides in `~/.config/dictate/options.conf` (read first) or
`~/.config/dictate/env` (read second, and where the API key lives). The environment wins
over both.

## If something goes wrong

The script appends a phase-by-phase timing log. It lives in `${XDG_RUNTIME_DIR}/dictate/`
(usually `/run/user/<uid>/dictate/`), falling back to `$TMPDIR/dictate-<uid>/`:

```bash
tail -20 "${XDG_RUNTIME_DIR:-/tmp}/dictate/timing.log"
```

The most recent recording is kept at `/tmp/dictate-last.flac`, so you can play it back
and hear whether the microphone captured what you thought it did.

If nothing is inserted, check in this order: is the timing log reaching `api: http=200`
(the request worked), and does `insert: done rc=0` appear (the paste landed)? That
distinguishes a transcription problem from a window-focus problem.

## Design

Read [docs/DESIGN.md](docs/DESIGN.md) before changing the script. It records the
measurements behind the current design and the traps that are easy to reintroduce —
particularly why insertion is a paste, why the clipboard write and keystroke must be
atomic, and why forcing insertion into recording order causes silent data loss.

## Tests

```bash
bash tests/suite.sh
```

Runs five scenarios against the live API using synthesised audio — no microphone needed.
It makes a few real API calls, costing a fraction of a cent. Set `N=` to the path of the
script under test if you are not testing the installed copy.

## Privacy

Audio is sent to OpenAI for transcription; that is the point of the tool. Recordings are
deleted after upload, except the single debug copy at `/tmp/dictate-last.flac`, which is
overwritten each time. Remove that line if you dictate anything sensitive.

## Licence

Apache License 2.0. See the repository [LICENSE](../../LICENSE).
