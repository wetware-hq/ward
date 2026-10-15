#!/usr/bin/env bash
# Fresh-clone safety bar. Sets every setting the five prepush checks read, then runs them in order.
#   scripts/bar.sh SIBLINGS [--env]
# SIBLINGS: the directory holding the clones (forms/ orders/ letters/ figures/ cards/ stack/) and the read-only
# folders below. --env prints the settings and runs nothing. Nothing here writes to the answer or wording folders.
#   stack_truth/    scenario answer files   -> STACK_TRUTH, LETTERS_TRUTH (letters reads <id>-*/truth.toml)
#   cards_truth/    cards answer files      -> CARDS_TRUTH
#   cards_wording/  cards wording answers   -> CARDS_WORDING
#   wording/        signing files           -> WORDING_DIRS, REUSED_SIGNED (forms_orders_lines_SIGNED.md),
#                                              CARDS_SIGNED (cards_lines_SIGNED.md)
# Unset any of these and the matching prepush fails (RUN-TRACES-NOT-RUN, or needs_signed tests deselected).
set -u
S="$(cd "${1:?usage: scripts/bar.sh SIBLINGS [--env]}" && pwd)"
export STACK_SIBLINGS_DIR="$S"
export STACK_TRUTH="$S/stack_truth" LETTERS_TRUTH="$S/stack_truth"
export CARDS_TRUTH="$S/cards_truth" CARDS_WORDING="$S/cards_wording"
export WORDING_DIRS="$S/wording" REUSED_SIGNED="$S/wording/forms_orders_lines_SIGNED.md"
export CARDS_SIGNED="$S/wording/cards_lines_SIGNED.md"
export MUTATE_WORKERS="${MUTATE_WORKERS:-4}"
for v in STACK_TRUTH CARDS_TRUTH CARDS_WORDING WORDING_DIRS REUSED_SIGNED CARDS_SIGNED; do
  [ -e "${!v}" ] || { echo "missing $v: ${!v}"; exit 2; }
done
case "$(realpath "$STACK_TRUTH")" in *.bak*) echo "refusing a backup answer folder"; exit 2;; esac
if [ "${2:-}" = "--env" ]; then
  env | grep -E '^(STACK_|LETTERS_TRUTH|CARDS_|WORDING_DIRS|REUSED_SIGNED|MUTATE_WORKERS)' | sed "s#$S#\$SIBLINGS#" | sort
  exit 0
fi
rc=0
run() { echo "== $1"; (cd "$S/$1" && shift && "$@") || { echo "!! $1 failed"; rc=1; }; }
run forms   python3 scripts/prepush.py "$REUSED_SIGNED"
run orders  python3 scripts/prepush.py "$REUSED_SIGNED"
run figures python3 scripts/prepush.py "$REUSED_SIGNED"
run letters python3 scripts/prepush.py
run cards   python3 scripts/prepush.py "$CARDS_SIGNED" "$REUSED_SIGNED"
run stack   python3 scripts/prepush.py
echo "bar: rc=$rc"; exit $rc
