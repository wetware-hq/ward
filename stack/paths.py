"""Where stack finds its sibling repos and the read-only truth dir. No absolute paths are written into the repo:
STACK_SIBLINGS_DIR (or the older STACK_WORKSPACE) names the directory holding forms/, orders/, letters/, figures/,
cards/, wording/ and stack_truth/; unset, it is the directory that holds this stack checkout."""
import os, pathlib

SIBLINGS = os.environ.get("STACK_SIBLINGS_DIR") or os.environ.get("STACK_WORKSPACE") \
    or str(pathlib.Path(__file__).resolve().parent.parent.parent)
TRUTH = os.environ.get("STACK_TRUTH") or os.path.join(SIBLINGS, "stack_truth")
