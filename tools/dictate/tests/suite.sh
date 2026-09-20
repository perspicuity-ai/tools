#!/usr/bin/env bash
# suite.sh — regression suite for dictate.
#
# Drives the real code paths against the live API using synthesised audio, so no
# microphone is needed. Makes a handful of real API calls (a fraction of a cent).
#
#   bash tests/suite.sh
#   N=/path/to/dictate bash tests/suite.sh    # test a different copy
#
# Requires: sox, curl, jq, xdotool, xclip, python3 with tkinter, and a working
# DISPLAY. It opens its own Tk windows as paste targets and closes them again.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
N="${N:-$HERE/../dictate}"                                     # script under test
W="${W:-$(mktemp -d "${TMPDIR:-/tmp}/dictate-suite.XXXXXX")}"  # scratch area
CFG="$W/cfg"
export DISPLAY="${DISPLAY:-:0}"
PASS=0; FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

cleanup() {
    pkill -9 -f "paste_target.py $W" 2>/dev/null
    [[ "${KEEP_SCRATCH:-0}" == "1" ]] || rm -rf "$W"
}
trap cleanup EXIT

# The suite needs a key. Prefer the caller's real config, and keep it out of the
# scratch directory so a failed run cannot leave a key behind.
KEY_FILE="${DICTATE_KEY_FILE:-$HOME/.config/dictate/env}"
if [[ ! -f "$KEY_FILE" ]]; then
    echo "No API key file at $KEY_FILE." >&2
    echo "Set DICTATE_KEY_FILE, or create it with OPENAI_API_KEY=sk-..." >&2
    exit 2
fi

mkdir -p "$CFG"
cp "$KEY_FILE" "$CFG/env"
chmod 600 "$CFG/env"
printf '# domain vocabulary\nJanus\nScholar\nBibTeX\nLaTeX\n' > "$CFG/keywords.txt"
printf 'Dictation of research notes about an academic paper toolchain.\n' > "$CFG/context.txt"

fresh_clip() { # $1 = name
    curl -sSL -m 40 -o "$W/base.wav" \
      "https://raw.githubusercontent.com/ggerganov/whisper.cpp/master/samples/jfk.wav" 2>/dev/null
    sox "$W/base.wav" -r 16000 -c 1 -b 16 "$W/$1" 2>/dev/null
}

echo "=== T1. syntax + guard ==="
bash -n "$N" && ok "parses" || bad "parse error"
out=$(DICTATE_SOURCED=1 DICTATE_STATE_DIR="$W/s1" bash -c "source '$N'; type -t transcribe_and_insert" 2>&1)
[[ "$out" == "function" ]] && ok "worker guard: sourcing is side-effect free" || bad "guard broken: $out"

echo
echo "=== T2. single utterance end-to-end (API + paste + clipboard preserved) ==="
rm -rf "$W/s2"; mkdir -p "$W/s2"
fresh_clip clip.flac
rm -f "$W/win.id" "$W/result.txt"
nohup python3 "$HERE/paste_target.py" "$W/win.id" "$W/result.txt" 3.0 >"$W/t.log" 2>&1 &
TP=$!
for _ in $(seq 1 80); do [[ -s "$W/win.id" ]] && break; sleep 0.1; done
WID=$(cat "$W/win.id"); sleep 0.5
printf 'MY-IMPORTANT-CLIPBOARD' | xclip -selection clipboard -i; sleep 0.4

env -i DISPLAY="$DISPLAY" HOME="$HOME" PATH="$PATH" XDG_CONFIG_HOME="$W" \
  DICTATE_STATE_DIR="$W/s2" DICTATE_SOURCED=1 DICTATE_TIMING_LOG="$W/s2/timing.log" \
  DICTATE_DEBUG_AUDIO="$W/s2/dbg" DICTATE_NOTIFY=0 DICTATE_INSERT=paste \
  bash -c "source '$N'; source '$CFG/env'; save_clipboard; transcribe_and_insert '$W/clip.flac' 1 '$WID' 11.0" \
  >"$W/s2/w.log" 2>&1
for _ in $(seq 1 150); do kill -0 $TP 2>/dev/null || break; sleep 0.1; done
kill -9 $TP 2>/dev/null
GOT=$(cat "$W/result.txt" 2>/dev/null)
[[ "$GOT" == *"ask not what your country can do for you"* ]] \
  && ok "transcript pasted into a real window" || bad "paste failed: [$GOT]"
grep -q "insert: done rc=0" "$W/s2/timing.log" && ok "insert reported success" || bad "insert failed"
sleep 5
CLIP=$(xclip -selection clipboard -o 2>/dev/null)
[[ "$CLIP" == "MY-IMPORTANT-CLIPBOARD" ]] && ok "clipboard restored after dictation" || bad "clipboard not restored: [$CLIP]"

echo
echo "=== T3. two concurrent workers: both transcripts arrive intact ==="
rm -rf "$W/s3"; mkdir -p "$W/s3"
for s in 1 2; do fresh_clip "c$s.flac"; done
rm -f "$W/win.id" "$W/result.txt"
nohup python3 "$HERE/paste_target.py" "$W/win.id" "$W/result.txt" 6.0 >"$W/t3.log" 2>&1 &
TP=$!
for _ in $(seq 1 80); do [[ -s "$W/win.id" ]] && break; sleep 0.1; done
WID=$(cat "$W/win.id"); sleep 0.5
for s in 1 2; do
  env -i DISPLAY="$DISPLAY" HOME="$HOME" PATH="$PATH" XDG_CONFIG_HOME="$W" \
    DICTATE_STATE_DIR="$W/s3" DICTATE_SOURCED=1 DICTATE_TIMING_LOG="$W/s3/timing.log" \
    DICTATE_DEBUG_AUDIO="$W/s3/dbg$s" DICTATE_NOTIFY=0 DICTATE_INSERT=paste \
    DICTATE_KEEP_CLIPBOARD=1 \
    bash -c "source '$N'; source '$CFG/env'; transcribe_and_insert '$W/c$s.flac' $s '$WID' 11.0" \
    >"$W/s3/w$s.log" 2>&1 &
  sleep 0.05
done
for _ in $(seq 1 400); do kill -0 $TP 2>/dev/null || break; sleep 0.1; done
kill -9 $TP 2>/dev/null
COUNT=$(grep -o "And so, my fellow Americans" "$W/result.txt" 2>/dev/null | wc -l)
[[ "$COUNT" -eq 2 ]] && ok "both transcripts arrived (no text lost): count=$COUNT" \
                     || bad "expected 2 transcripts, got $COUNT"
INTERLEAVED=$(grep -c "insert: done rc=0" "$W/s3/timing.log")
[[ "$INTERLEAVED" -eq 2 ]] && ok "both inserts completed" || bad "inserts=$INTERLEAVED"

echo
echo "=== T4. failure path: bad key must fail cleanly, not strand state ==="
rm -rf "$W/s4"; mkdir -p "$W/s4"
fresh_clip c4.flac
env -i DISPLAY="$DISPLAY" HOME="$HOME" PATH="$PATH" XDG_CONFIG_HOME="$W" \
  DICTATE_STATE_DIR="$W/s4" DICTATE_SOURCED=1 DICTATE_TIMING_LOG="$W/s4/timing.log" \
  DICTATE_DEBUG_AUDIO="$W/s4/dbg" DICTATE_NOTIFY=0 OPENAI_API_KEY=sk-invalid-key \
  DICTATE_API_RETRIES=0 \
  bash -c "source '$N'; transcribe_and_insert '$W/c4.flac' 1 '' 11.0" \
  >"$W/s4/w.log" 2>&1
RC=$?
[[ "$RC" -eq 1 ]] && ok "bad key exits non-zero (rc=$RC)" || bad "expected rc=1, got rc=$RC"
grep -q "api: FAILED 401" "$W/s4/timing.log" && ok "401 recorded in timing log" || bad "no 401 in log"

echo
echo "=== T5. type fallback works when xclip is unavailable ==="
rm -rf "$W/s5"; mkdir -p "$W/s5"
fresh_clip c5.flac
rm -f "$W/win.id" "$W/result.txt"
nohup python3 "$HERE/paste_target.py" "$W/win.id" "$W/result.txt" 3.0 >"$W/t5.log" 2>&1 &
TP=$!
for _ in $(seq 1 80); do [[ -s "$W/win.id" ]] && break; sleep 0.1; done
WID=$(cat "$W/win.id"); sleep 0.5
TBIN="$W/nobin"; mkdir -p "$TBIN"
# Deliberately omit xclip: the script must detect its absence and type instead.
for b in bash curl sox soxi jq date stat sed grep xargs flock nohup sleep kill pgrep \
         awk tail rm cat printf head tr wc mkdir cp id uname; do
    p=$(command -v $b 2>/dev/null) && ln -sf "$p" "$TBIN/$b" 2>/dev/null
done
ln -sf "$(command -v xdotool)" "$TBIN/xdotool"
PATH="$TBIN" DISPLAY="$DISPLAY" HOME="$HOME" XDG_CONFIG_HOME="$W" \
  DICTATE_STATE_DIR="$W/s5" DICTATE_SOURCED=1 DICTATE_TIMING_LOG="$W/s5/timing.log" \
  DICTATE_DEBUG_AUDIO="$W/s5/dbg" DICTATE_NOTIFY=0 DICTATE_INSERT=paste DICTATE_TYPE_DELAY=2 \
  bash -c "source '$N'; source '$CFG/env'; transcribe_and_insert '$W/c5.flac' 1 '$WID' 11.0" \
  >"$W/s5/w.log" 2>&1
for _ in $(seq 1 150); do kill -0 $TP 2>/dev/null || break; sleep 0.1; done
kill -9 $TP 2>/dev/null
GOT5=$(cat "$W/result.txt" 2>/dev/null)
[[ "$GOT5" == *"ask not what your country can do for you"* ]] \
  && ok "fallback typed the text without xclip" || bad "fallback failed: [$GOT5]"

echo
echo "==================================="
echo "  PASSED: $PASS    FAILED: $FAIL"
echo "==================================="
