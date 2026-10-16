"""Local names come from the site profile; the blank TEMPLATE fails closed."""
import os, pytest
from ward import site_profile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_test_profile_gives_reader():
    assert site_profile.family_doctor().strip()


def test_template_is_blank_and_fails_closed():
    with pytest.raises(ValueError):
        site_profile.load(os.path.join(HERE, "examples", "site_profile_TEMPLATE.toml"))


def test_profile_comes_from_configuration(monkeypatch, tmp_path):
    p = tmp_path / "p.toml"; p.write_text('[family_doctor]\nreader = "X-DOC"\ncite = "TEST"\n')
    monkeypatch.setenv("WARD_SITE_PROFILE", str(p))
    assert site_profile.family_doctor(site_profile.configured()) == "X-DOC"


def test_core_names_no_profile_file():
    src = open(os.path.join(HERE, "ward", "site_profile.py")).read()
    assert "EXAMPLE" not in src and "site_profiles" not in src
