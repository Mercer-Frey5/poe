"""
test_v04_foundations.py — test fondazioni v0.4.

Copre:
  - Schema Entity esteso (confidence, metadata, derived_from)
  - Backfill storage per entità storiche v0.2/v0.3
  - Confidence corretta per tipo estratto
  - Metadata phone (country_code, national_number)
  - Flag kept in storage (C2 fase 1)
"""

from __future__ import annotations

import json
import pytest

from app import storage
from app.models import Entity, _VALID_CONFIDENCE


# ─────────────────────────────────────────────────────────────
# Entity schema
# ─────────────────────────────────────────────────────────────

class TestEntitySchema:
    def test_default_confidence_is_medium(self):
        e = Entity("email", "a@b.com")
        assert e.confidence == "medium"

    def test_default_metadata_is_empty_dict(self):
        e = Entity("email", "a@b.com")
        assert e.metadata == {}

    def test_default_derived_from_is_none(self):
        e = Entity("email", "a@b.com")
        assert e.derived_from is None

    def test_explicit_confidence_high(self):
        e = Entity("phone", "+391234567890", confidence="high")
        assert e.confidence == "high"

    def test_explicit_confidence_low(self):
        e = Entity("username", "@foo", confidence="low")
        assert e.confidence == "low"

    def test_invalid_confidence_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            Entity("email", "a@b.com", confidence="very_high")

    def test_metadata_stored(self):
        e = Entity("phone", "+391234567890", confidence="high",
                   metadata={"country_code": 39, "national_number": 1234567890})
        assert e.metadata["country_code"] == 39
        assert e.metadata["national_number"] == 1234567890

    def test_derived_from_stored(self):
        e = Entity("domain", "evil.com", derived_from="url:https://evil.com/x")
        assert e.derived_from == "url:https://evil.com/x"

    def test_hash_excludes_confidence_and_metadata(self):
        e1 = Entity("email", "a@b.com", confidence="high")
        e2 = Entity("email", "a@b.com", confidence="low", metadata={"k": "v"})
        # Stessa identità: hash e __eq__ ignorano confidence/metadata
        assert e1 == e2
        assert hash(e1) == hash(e2)

    def test_to_dict_includes_all_v04_fields(self):
        e = Entity("phone", "+391234567890", confidence="high",
                   metadata={"country_code": 39})
        d = e.to_dict()
        assert "confidence" in d
        assert "metadata" in d
        assert "derived_from" in d
        assert d["confidence"] == "high"
        assert d["metadata"]["country_code"] == 39

    def test_valid_confidence_values(self):
        assert _VALID_CONFIDENCE == {"high", "medium", "low"}


# ─────────────────────────────────────────────────────────────
# Confidence per tipo estratto
# ─────────────────────────────────────────────────────────────

class TestConfidenceByType:
    def _conf(self, entities, type_):
        return {e.confidence for e in entities if e.type == type_}

    def test_email_confidence_medium(self, regex_extractor):
        e = regex_extractor.extract("user@example.com")
        assert self._conf(e, "email") == {"medium"}

    def test_ipv4_confidence_medium(self, regex_extractor):
        e = regex_extractor.extract("IP: 1.2.3.4")
        assert self._conf(e, "ipv4") == {"medium"}

    def test_url_confidence_medium(self, regex_extractor):
        e = regex_extractor.extract("https://example.com")
        assert self._conf(e, "url") == {"medium"}

    def test_domain_confidence_medium(self, regex_extractor):
        e = regex_extractor.extract("evil.com")
        assert self._conf(e, "domain") == {"medium"}

    def test_hash_md5_confidence_medium(self, regex_extractor):
        e = regex_extractor.extract("44d88612fea8a8f36de82e1278abb02f")
        assert self._conf(e, "hash_md5") == {"medium"}

    def test_hash_sha256_confidence_medium(self, regex_extractor):
        h = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        e = regex_extractor.extract(h)
        assert self._conf(e, "hash_sha256") == {"medium"}

    def test_cve_confidence_medium(self, regex_extractor):
        e = regex_extractor.extract("CVE-2024-12345")
        assert self._conf(e, "cve") == {"medium"}

    def test_social_handle_supersedes_username(self, regex_extractor):
        # Dedup: @handle viene estratto come social_handle (medium), non username
        e = regex_extractor.extract("@mrossi_official")
        assert self._conf(e, "social_handle") == {"medium"}
        assert self._conf(e, "username") == set()

    def test_phone_confidence_high(self, regex_extractor):
        e = regex_extractor.extract("+39 347 1234567")
        assert self._conf(e, "phone") == {"high"}

    def test_person_name_confidence_low(self, fake_spacy):
        from app.extractors.spacy_extractor import SpacyExtractor
        from app.recognizer import Recognizer
        from app.extractors.regex_extractor import RegexExtractor
        spacy = fake_spacy([Entity("person_name", "Mario Rossi", confidence="low")])
        rec = Recognizer(RegexExtractor(), spacy)
        entities = rec.recognize("Mario Rossi ha scritto a user@example.com")
        pn = [e for e in entities if e.type == "person_name"]
        assert all(e.confidence == "low" for e in pn)


# ─────────────────────────────────────────────────────────────
# Metadata phone
# ─────────────────────────────────────────────────────────────

class TestPhoneMetadata:
    def test_phone_has_country_code(self, regex_extractor):
        e = regex_extractor.extract("+39 347 1234567")
        phones = [x for x in e if x.type == "phone"]
        assert len(phones) == 1
        assert phones[0].metadata["country_code"] == 39

    def test_phone_has_national_number(self, regex_extractor):
        e = regex_extractor.extract("+39 347 1234567")
        phones = [x for x in e if x.type == "phone"]
        assert "national_number" in phones[0].metadata

    def test_phone_uk_country_code(self, regex_extractor):
        e = regex_extractor.extract("+44 20 7946 0958")
        phones = [x for x in e if x.type == "phone"]
        assert len(phones) == 1
        assert phones[0].metadata["country_code"] == 44


# ─────────────────────────────────────────────────────────────
# Backfill storage
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(storage, "DB_PATH", db_file)
    storage.init_db()
    return db_file


class TestStorageBackfill:
    def test_v03_entity_gets_confidence_backfill(self, temp_db):
        with storage._connect() as conn:
            conn.execute(
                "INSERT INTO observations (timestamp, raw_input, entities_json, kept) "
                "VALUES (?, ?, ?, ?)",
                ("2024-01-01T00:00:00", "legacy",
                 json.dumps([{"type": "email", "value": "a@b.com", "original": "a@b.com"}]),
                 0),
            )
        rows = storage.get_recent(limit=1)
        e = rows[0]["entities"][0]
        assert e["confidence"] == "medium"
        assert e["metadata"] == {}
        assert e["derived_from"] is None

    def test_v01_entity_full_backfill(self, temp_db):
        with storage._connect() as conn:
            conn.execute(
                "INSERT INTO observations (timestamp, raw_input, entities_json, kept) "
                "VALUES (?, ?, ?, ?)",
                ("2024-01-01T00:00:00", "v0.1",
                 json.dumps([{"type": "ipv4", "value": "1.2.3.4"}]),
                 0),
            )
        rows = storage.get_recent(limit=1)
        e = rows[0]["entities"][0]
        assert e["original"] == "1.2.3.4"
        assert e["confidence"] == "medium"
        assert e["metadata"] == {}

    def test_v04_entity_round_trip(self, temp_db):
        entities = [
            Entity("phone", "+393471234567", confidence="high",
                   metadata={"country_code": 39, "national_number": 3471234567}),
            Entity("email", "a@b.com", confidence="medium"),
        ]
        obs_id = storage.save_observation("test", entities)
        retrieved = storage.get_by_id(obs_id)
        phone_e = next(e for e in retrieved["entities"] if e["type"] == "phone")
        assert phone_e["confidence"] == "high"
        assert phone_e["metadata"]["country_code"] == 39

    def test_kept_default_false(self, temp_db):
        obs_id = storage.save_observation("test", [])
        retrieved = storage.get_by_id(obs_id)
        assert retrieved["kept"] is False

    def test_set_kept_true(self, temp_db):
        obs_id = storage.save_observation("test", [])
        storage.set_kept(obs_id, True)
        retrieved = storage.get_by_id(obs_id)
        assert retrieved["kept"] is True

    def test_set_kept_false(self, temp_db):
        obs_id = storage.save_observation("test", [])
        storage.set_kept(obs_id, True)
        storage.set_kept(obs_id, False)
        retrieved = storage.get_by_id(obs_id)
        assert retrieved["kept"] is False

    def test_filter_kept(self, temp_db):
        id1 = storage.save_observation("prima", [])
        id2 = storage.save_observation("seconda", [])
        storage.set_kept(id1, True)
        kept = storage.get_recent(limit=10, filter_kept='kept')
        draft = storage.get_recent(limit=10, filter_kept='draft')
        assert any(r["id"] == id1 for r in kept)
        assert all(r["id"] != id1 for r in draft)
        assert any(r["id"] == id2 for r in draft)
