"""Where stack finds its sibling repos and the read-only answer files (truth). No absolute paths are written into the
repo. STACK_SIBLINGS_DIR (or the older STACK_WORKSPACE) names the directory holding forms/, orders/, letters/,
figures/, cards/ and wording/; unset, it is the directory that holds this stack checkout.
The answer-file directory is a setting only: STACK_TRUTH, or `truth = "..."` in the untracked stack.local.toml at the
repo root. Unset, TRUTH is None and the traces are not run (RUN-TRACES-NOT-RUN)."""
import os, pathlib, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIBLINGS = os.environ.get("STACK_SIBLINGS_DIR") or os.environ.get("STACK_WORKSPACE") or str(ROOT.parent)
NOT_RUN = "RUN-TRACES-NOT-RUN"


def _truth():
    if os.environ.get("STACK_TRUTH"):
        return os.environ["STACK_TRUTH"]
    local = ROOT / "stack.local.toml"
    return tomllib.loads(local.read_text()).get("truth") if local.is_file() else None


TRUTH = _truth()
