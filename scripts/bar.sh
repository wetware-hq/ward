#!/usr/bin/env bash
# Fresh-clone safety bar. Sets every setting the five prepush checks read, then runs them in order.
#   scripts/bar.sh SIBLINGS [--env]
# SIBLINGS: the directory holding the clones (forms/ orders/ letters/ figures/ cards/ ward/) and the read-only
# folders below. --env prints the settings and runs nothing. Nothing here writes to the answer or wording folders.
#   stack_truth/    scenario answer files   -> WARD_TRUTH, LETTERS_TRUTH (letters reads <id>-*/truth.toml)
#   cards_truth/    cards answer files      -> CARDS_TRUTH
#   cards_wording/  cards wording answers   -> CARDS_WORDING
#   wording/        signing files           -> WORDING_DIRS, REUSED_SIGNED (forms_orders_lines_SIGNED.md),
#                                              CARDS_SIGNED (cards_lines_SIGNED.md)
# Unset any of these and the matching prepush fails (RUN-TRACES-NOT-RUN, or needs_signed tests deselected).
set -u
S="$(cd "${1:?usage: scripts/bar.sh SIBLINGS [--env]}" && pwd)"
export WARD_SIBLINGS_DIR="$S"
export WARD_TRUTH="$S/stack_truth" LETTERS_TRUTH="$S/stack_truth"
export CARDS_TRUTH="$S/cards_truth" CARDS_WORDING="$S/cards_wording"
export WORDING_DIRS="$S/wording" REUSED_SIGNED="$S/wording/forms_orders_lines_SIGNED.md"
export CARDS_SIGNED="$S/wording/cards_lines_SIGNED.md"
# figures needs its packages; a fresh clone has no figures/.venv — require an interpreter that can import them
if [ -z "${WARD_FIGURES_PYTHON:-}" ]; then
  if [ -x "$S/figures/.venv/bin/python" ]; then WARD_FIGURES_PYTHON="$S/figures/.venv/bin/python"
  else echo "set WARD_FIGURES_PYTHON to a Python that can import figures' packages (fresh clone has no figures/.venv)"; exit 2
  fi
fi
export WARD_FIGURES_PYTHON
unset WARD_MODEL_API_KEY $(compgen -e | grep '^OPENROUTER' || true)   # scripted only: no model key reaches any run
export MUTATE_WORKERS="${MUTATE_WORKERS:-4}"
for r in forms orders figures letters cards ward; do       # every repo by name; fail loudly when one is missing
  [ -d "$S/$r" ] || { echo "missing repo: $r"; [ "$r" = ward ] && [ -d "$S/st""ack" ] && echo "found the old name st""ack/: rename it to ward/"; exit 2; }
done
for v in WARD_TRUTH CARDS_TRUTH CARDS_WORDING WORDING_DIRS REUSED_SIGNED CARDS_SIGNED; do
  [ -e "${!v}" ] || { echo "missing $v: ${!v}"; exit 2; }
done
case "$(realpath "$WARD_TRUTH")" in *.bak*) echo "refusing a backup answer folder"; exit 2;; esac
if [ "${2:-}" = "--env" ]; then
  echo "unset WARD_MODEL_API_KEY OPENROUTER*"
  env | grep -E '^(WARD_|LETTERS_TRUTH|CARDS_|WORDING_DIRS|REUSED_SIGNED|MUTATE_WORKERS)' | sed "s#$S#\$SIBLINGS#" | sort
  exit 0
fi
rc=0
KEEP="WARD_SIBLINGS_DIR WARD_TRUTH LETTERS_TRUTH CARDS_TRUTH CARDS_WORDING WORDING_DIRS REUSED_SIGNED CARDS_SIGNED WARD_FIGURES_PYTHON MUTATE_WORKERS"
PROBE="$S/ward/scripts/key_probe.py"
# each run is a child with a whitelisted environment (env -i); the key probe runs in it before any test code
run() {
  local d="$S/$1"; shift; echo "== ${d##*/}"
  local e=(PATH="$PATH" HOME="$HOME" LANG="${LANG:-C.UTF-8}"); for v in $KEEP; do e+=("$v=${!v}"); done
  (cd "$d" && env -i "${e[@]}" sh -c 'python3 "$0" . && exec "$@"' "$PROBE" "$@") || { echo "!! ${d##*/} failed"; rc=1; }
}
run forms   python3 scripts/prepush.py "$REUSED_SIGNED"
run orders  python3 scripts/prepush.py "$REUSED_SIGNED"
run figures python3 scripts/prepush.py "$REUSED_SIGNED"
run letters python3 scripts/prepush.py
run cards   python3 scripts/prepush.py "$CARDS_SIGNED" "$REUSED_SIGNED"
"$WARD_FIGURES_PYTHON" -c "import polars,matplotlib" 2>/dev/null || { echo "WARD_FIGURES_PYTHON=$WARD_FIGURES_PYTHON cannot import polars/matplotlib"; exit 2; }
run ward   python3 scripts/prepush.py
echo "bar: rc=$rc"; exit $rc
