"""Site profile: local names and values (here, the reader word for the family doctor) are data, not code.
The profile path comes from configuration: WARD_SITE_PROFILE, else `profile` in config/site.toml (relative to
the repo). No profile name is hard-coded here. A missing setting or an empty value fails closed."""
import os, tomllib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(HERE, "config", "site.toml")


def configured():
    p = os.environ.get("WARD_SITE_PROFILE")
    if not p and os.path.isfile(CONFIG):
        p = tomllib.load(open(CONFIG, "rb")).get("profile", "")
    if not p:
        raise ValueError("site profile: not configured (WARD_SITE_PROFILE or config/site.toml)")
    return p if os.path.isabs(p) else os.path.join(HERE, p)


def load(path=None):
    d = tomllib.load(open(path or configured(), "rb"))
    v = d.get("family_doctor", {}).get("reader", "")
    if not v.strip():
        raise ValueError("site profile: family_doctor.reader is empty")
    return d


def family_doctor(path=None):
    return load(path)["family_doctor"]["reader"]


FAMILY_DOCTOR = family_doctor()
