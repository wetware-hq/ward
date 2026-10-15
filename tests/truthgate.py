"""Answer-file gate for tests: with no answer-file setting a trace test is skipped as RUN-TRACES-NOT-RUN (never
reported as passed); with the setting present a missing answer file fails the test, never skips it."""
import os, pytest
from stack import paths


def missing_truth(sid=""):
    if paths.TRUTH is None:
        pytest.skip(paths.NOT_RUN)
    pytest.fail(f"missing answer file {sid} under the answer-file setting".replace("  ", " "))


def truth_path(*parts):
    if paths.TRUTH is None:
        pytest.skip(paths.NOT_RUN)
    return os.path.join(paths.TRUTH, *parts)
