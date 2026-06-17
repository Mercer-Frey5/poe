"""
test_config_loader.py — test del loader YAML condiviso (app/config_loader.py).

Il loader unifica i 3 caricamenti che prima vivevano duplicati in
regex_extractor.py e spacy_extractor.py.
"""

from __future__ import annotations

import pytest

from app.config_loader import load_yaml_list, _CONFIG_DIR


class TestLoadYamlList:
    def test_loads_existing_seed(self):
        result = load_yaml_list("tld_list.yaml")
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(v, str) for v in result)

    def test_missing_file_raises(self):
        with pytest.raises(RuntimeError, match="mancante"):
            load_yaml_list("file_che_non_esiste_xyz.yaml")

    def test_malformed_file_raises(self, tmp_path, monkeypatch):
        bad = tmp_path / "bad.yaml"
        bad.write_text("non_una_lista: 42\n")
        monkeypatch.setattr("app.config_loader._CONFIG_DIR", tmp_path)
        with pytest.raises(RuntimeError, match="malformato"):
            load_yaml_list("bad.yaml")

    def test_empty_list_raises_by_default(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty.yaml"
        empty.write_text("[]\n")
        monkeypatch.setattr("app.config_loader._CONFIG_DIR", tmp_path)
        with pytest.raises(RuntimeError, match="vuoto"):
            load_yaml_list("empty.yaml")

    def test_empty_list_allowed_with_flag(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty.yaml"
        empty.write_text("[]\n")
        monkeypatch.setattr("app.config_loader._CONFIG_DIR", tmp_path)
        result = load_yaml_list("empty.yaml", allow_empty=True)
        assert result == []

    def test_filters_none_and_blank(self, tmp_path, monkeypatch):
        path = tmp_path / "messy.yaml"
        path.write_text("- foo\n- ~\n- '  '\n- bar\n")
        monkeypatch.setattr("app.config_loader._CONFIG_DIR", tmp_path)
        result = load_yaml_list("messy.yaml")
        assert result == ["foo", "bar"]
