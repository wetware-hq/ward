"""BK-NO-PACK reads the letters site-profile config, never a hard-coded letters/locale/<pack> folder."""
from ward import locales


def _letters(tmp_path, locale, profile, make_dir=True):
    (tmp_path / "letters" / "config").mkdir(parents=True)
    (tmp_path / "letters" / "config" / "site.toml").write_text(f'profile = "{profile}"\nlocale = "{locale}"\n')
    if make_dir:
        (tmp_path / "letters" / profile).mkdir(parents=True)


def test_configured_pack_exists(tmp_path, monkeypatch):
    _letters(tmp_path, "au", "examples/site_profile_au_EXAMPLE")
    monkeypatch.setattr(locales, "WORKSPACE", str(tmp_path))
    monkeypatch.delenv("LETTERS_SITE_PROFILE", raising=False)
    assert locales.pack_exists("au") and not locales.pack_exists("nz")


def test_missing_profile_folder_or_config_is_no_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(locales, "WORKSPACE", str(tmp_path))
    assert not locales.pack_exists("au")                      # no config at all
    _letters(tmp_path, "au", "examples/x", make_dir=False)
    assert not locales.pack_exists("au")
    (tmp_path / "letters" / "locale" / "au").mkdir(parents=True)   # an old-style folder alone is not enough
    assert not locales.pack_exists("au")
