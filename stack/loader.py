"""Load forms and orders side by side. Both ship top-level `messages` and `access` modules with the
same names, so a plain import of both in one process collides (interface gap G1). Each is loaded
with its own copies of those modules and kept under a private name."""
import importlib.util, os, sys

from stack.paths import SIBLINGS as WORKSPACE
_CACHE = {}


def load(repo, module):
    if repo in _CACHE:
        return _CACHE[repo]
    root = os.path.join(WORKSPACE, repo)
    saved = {k: sys.modules.pop(k) for k in ("messages", "access") if k in sys.modules}
    sys.path.insert(0, root)
    try:
        deps = {}
        for dep in ("messages", "access"):
            spec = importlib.util.spec_from_file_location(dep, os.path.join(root, dep + ".py"))
            m = importlib.util.module_from_spec(spec)
            sys.modules[dep] = m
            spec.loader.exec_module(m)
            deps[dep] = m
        spec = importlib.util.spec_from_file_location(f"_stack_{repo}", os.path.join(root, module + ".py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._deps = deps
    finally:
        sys.path.remove(root)
        for k in ("messages", "access"):
            sys.modules.pop(k, None)
        sys.modules.update(saved)
    _CACHE[repo] = mod
    return mod


def forms():
    return load("forms", "forms")


def orders():
    return load("orders", "orders")
