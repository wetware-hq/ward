"""Site profile: local names and values (here, the reader word for the family doctor) are data, not code.
WARD_SITE_PROFILE picks the file; the default is the synthetic TEST profile. An empty value fails closed."""
import os, tomllib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(HERE, "data", "site_profiles", "test.toml")


def load(path=None):
    p = path or os.environ.get("WARD_SITE_PROFILE") or DEFAULT
    d = tomllib.load(open(p, "rb"))
    v = d.get("family_doctor", {}).get("reader", "")
    if not v.strip():
        raise ValueError("site profile: family_doctor.reader is empty")
    return d


def family_doctor(path=None):
    return load(path)["family_doctor"]["reader"]


FAMILY_DOCTOR = family_doctor()
