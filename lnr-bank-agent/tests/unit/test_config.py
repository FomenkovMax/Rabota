from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from lnrbank.config import CONFIG_DIR, Secrets, load_parameters, load_settings


def test_settings_load():
    s = load_settings()
    assert s.base_bank == "SBER"
    assert set(s.banks) == {"SBER", "VTB", "PSB", "TBANK"}
    assert s.blocks_mvp == ["DEP", "CARD", "LOAN", "MTG", "CHANNEL"]
    assert {"DEP-1", "MTG-2", "CAR-1"} <= set(s.scenarios)


def test_missing_banks_section_names_key(tmp_path: Path):
    data = yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8"))
    del data["banks"]
    bad = tmp_path / "settings.yaml"
    bad.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError, match="banks"):
        load_settings(bad)


def test_unknown_key_rejected(tmp_path: Path):
    data = yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8"))
    data["gigachat_credentials"] = "leak"
    bad = tmp_path / "settings.yaml"
    bad.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(bad)


def test_parameters_cover_mvp_blocks():
    params = load_parameters()
    assert set(load_settings().blocks_mvp) <= set(params)
    for block in params.values():
        for name in block:
            assert name == name.lower() and " " not in name


def test_secrets_from_env_only(monkeypatch):
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret-value")
    s = Secrets(_env_file=None)
    assert s.gigachat_credentials.get_secret_value() == "secret-value"
    assert "secret-value" not in repr(s)
