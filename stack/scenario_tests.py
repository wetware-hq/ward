"""Stack implementations of the [[scenario_tests]] declared in truth files. A declared test with no
implementation here reports 'not implemented' (a fail), never a pass."""

IMPLEMENTED = {}


def run_declared(sid, declared, h):
    out = {}
    for t in declared:
        fn = IMPLEMENTED.get(t.get("id"))
        out[t.get("id")] = fn(h, t) if fn else "not implemented"
    return out
