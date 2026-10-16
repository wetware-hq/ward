"""Local names come from the site profile; the blank TEMPLATE fails closed."""
import os, pytest
from ward import site_profile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_test_profile_gives_reader():
    assert site_profile.family_doctor().strip()


def test_template_is_blank_and_fails_closed():
    with pytest.raises(ValueError):
        site_profile.load(os.path.join(HERE, "data", "site_profiles", "template.toml"))
