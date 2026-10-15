"""Where ward finds its sibling repos and the read-only answer files (truth). No absolute paths are written into the
repo. WARD_SIBLINGS_DIR (or the older WARD_WORKSPACE) names the directory holding forms/, orders/, letters/,
figures/, cards/ and wording/; unset, it is the directory that holds this ward checkout.
The answer-file directory is a setting only: WARD_TRUTH, or `truth = "..."` in the untracked ward.local.toml at the
repo root. Unset, TRUTH is None and the traces are not run (RUN-TRACES-NOT-RUN)."""
import os, pathlib, tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIBLINGS = os.environ.get("WARD_SIBLINGS_DIR") or os.environ.get("WARD_WORKSPACE") or str(ROOT.parent)
NOT_RUN = "RUN-TRACES-NOT-RUN"


def _truth():
    if os.environ.get("WARD_TRUTH"):
        return os.environ["WARD_TRUTH"]
    local = ROOT / "ward.local.toml"
    return tomllib.loads(local.read_text()).get("truth") if local.is_file() else None


TRUTH = _truth()
