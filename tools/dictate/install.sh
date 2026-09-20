#!/usr/bin/env bash
# install.sh — install dictate to ~/.local/bin and seed its configuration.
#
# Safe to re-run. It never overwrites an existing API key file.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${DICTATE_BIN_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dictate"

say() { printf '  %s\n' "$1"; }
warn() { printf '  ! %s\n' "$1" >&2; }

echo "dictate installer"
echo

# --- required external commands ---------------------------------------------
missing=()
for cmd in sox rec soxi curl jq xdotool xclip; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
if (( ${#missing[@]} > 0 )); then
    warn "missing required commands: ${missing[*]}"
    case "$(uname -s)" in
        Linux)
            if command -v apt-get >/dev/null 2>&1; then
                say "on Debian/Ubuntu:  sudo apt install sox curl jq xdotool xclip"
            elif command -v dnf >/dev/null 2>&1; then
                say "on Fedora:         sudo dnf install sox curl jq xdotool xclip"
            elif command -v pacman >/dev/null 2>&1; then
                say "on Arch:           sudo pacman -S sox curl jq xdotool xclip"
            fi
            ;;
    esac
    echo
    warn "install those first, then re-run this script"
    exit 1
fi
say "all required commands found"

if ! command -v notify-send >/dev/null 2>&1; then
    warn "notify-send not found; set DICTATE_NOTIFY=0 to silence that warning"
fi

# --- the tool ---------------------------------------------------------------
mkdir -p "$BIN_DIR"
install -m 755 "$HERE/dictate" "$BIN_DIR/dictate"
say "installed $BIN_DIR/dictate"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not on your PATH; add it to your shell profile" ;;
esac

# --- configuration ----------------------------------------------------------
mkdir -p "$CONFIG_DIR"

if [[ -f "$CONFIG_DIR/env" ]]; then
    say "kept existing $CONFIG_DIR/env"
else
    cat > "$CONFIG_DIR/env" <<'EOF'
# dictate configuration. The API key is required; everything else is optional.
OPENAI_API_KEY=
EOF
    chmod 600 "$CONFIG_DIR/env"
    say "created $CONFIG_DIR/env (add your key)"
fi

if [[ -f "$CONFIG_DIR/keywords.txt" ]]; then
    say "kept existing $CONFIG_DIR/keywords.txt"
else
    cat > "$CONFIG_DIR/keywords.txt" <<'EOF'
# Vocabulary hints, one literal term per line.
# Names, acronyms and jargon the transcriber would otherwise mishear.
# Keep it short: these are hints, and irrelevant entries can leak into output.
EOF
    say "created $CONFIG_DIR/keywords.txt (add your vocabulary)"
fi

if [[ ! -f "$CONFIG_DIR/context.txt" ]]; then
    printf 'Dictation of ordinary prose.\n' > "$CONFIG_DIR/context.txt"
    say "created $CONFIG_DIR/context.txt"
fi

if [[ ! -f "$CONFIG_DIR/options.conf" ]]; then
    cat > "$CONFIG_DIR/options.conf" <<'EOF'
# Optional dictate settings. Read before `env`; the real environment wins over both.
# Example:
# DICTATE_PASTE_KEY=ctrl+shift+v     # when dictating into a terminal
# DICTATE_MODEL=gpt-4o-transcribe    # to pin a different model
EOF
    say "created $CONFIG_DIR/options.conf"
fi

# --- next steps -------------------------------------------------------------
echo
if grep -qE '^OPENAI_API_KEY=.+$' "$CONFIG_DIR/env" 2>/dev/null; then
    say "API key present"
else
    echo "Next: add your OpenAI API key"
    echo "  printf 'OPENAI_API_KEY=sk-...\\n' > $CONFIG_DIR/env"
    echo "  chmod 600 $CONFIG_DIR/env"
    echo
fi
echo "Then bind a global hotkey to: $BIN_DIR/dictate"
echo "See README.md for hotkey setup, vocabulary hints and troubleshooting."
