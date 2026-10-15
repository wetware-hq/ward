"""Independent probe, run inside each scripted child before any test code: exit 3 loudly if a model key can be
reached: WARD_MODEL_API_KEY / OPENROUTER* names or an sk-or- value in the environment, a .env or config file in the
repo naming one, or ~/.config/openrouter. Prints names and paths only, never a value.
Usage: key_probe.py REPO"""
import os, re, subprocess, sys

NAME = re.compile(r"^(WARD_MODEL_API_KEY|OPENROUTER\w*)$")
VALUE = re.compile(r"sk-or-")
ASSIGN = re.compile(r"(?m)^\s*(?:export\s+)?(WARD_MODEL_API_KEY|OPENROUTER\w*)\s*[=:]")
CONFIG = re.compile(r"(^|/)\.env[^/]*$|\.(toml|ini|cfg|conf|json|ya?ml)$")


def findings(repo, env=os.environ, home=None):
    out = [f"env name {k}" for k in env if NAME.match(k)]
    out += [f"env value of {k} looks like a key" for k, v in env.items() if VALUE.search(v)]
    try:
        files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=repo, capture_output=True,
                               text=True, check=True).stdout.split("\n")
    except (OSError, subprocess.CalledProcessError):
        files = [os.path.relpath(os.path.join(d, f), repo) for d, _, fs in os.walk(repo) for f in fs]
    files += [f for f in os.listdir(repo) if f.startswith(".env")]          # ignored .env files too
    for f in sorted(set(x for x in files if x and CONFIG.search(x))):
        try:
            t = open(os.path.join(repo, f), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if VALUE.search(t) or ASSIGN.search(t):
            out.append(f"repo file {f}")
    cfg = os.path.join(home if home is not None else os.path.expanduser("~"), ".config", "openrouter")
    if os.path.exists(cfg):
        out.append(f"{cfg} exists")
    return out


if __name__ == "__main__":
    f = findings(sys.argv[1] if len(sys.argv) > 1 else ".")
    if f:
        print("KEY PROBE FAILED: a model key is reachable in a scripted run:\n  " + "\n  ".join(f), file=sys.stderr)
        sys.exit(3)
    print("key probe: no model key reachable")
