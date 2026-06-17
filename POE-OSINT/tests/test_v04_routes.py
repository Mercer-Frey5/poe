"""
test_v04_routes.py — test per le nuove route e helper di v0.4.

Copre:
  - _compute_score: pesi per confidence + bonus varietà
  - _build_markdown: formato export C3
  - _render_kept_toggle: HTML corretto per stato kept/draft
  - POST /e/{id}/keep: toggle kept via HTMX (C2)
  - GET /e/{id}/export.md: download Markdown (C3)
  - GET / con filtro ?view= (C2 filter)
"""

from __future__ import annotations

import pytest

from app import storage
from app.main import _render_kept_toggle
from app.scoring import compute_score as _compute_score, build_markdown as _build_markdown
from app.models import Entity


# ─────────────────────────────────────────────────────────────
# _compute_score
# ─────────────────────────────────────────────────────────────

class TestComputeScore:
    def test_empty_returns_zero(self):
        assert _compute_score([]) == 0

    def test_single_high(self):
        e = [{"type": "phone", "confidence": "high"}]
        assert _compute_score(e) == 3 + 2  # 3 + 1 tipo * 2

    def test_single_medium(self):
        e = [{"type": "email", "confidence": "medium"}]
        assert _compute_score(e) == 2 + 2

    def test_single_low(self):
        e = [{"type": "birth_date", "confidence": "low"}]
        assert _compute_score(e) == 1 + 2

    def test_variety_bonus_two_types(self):
        e = [
            {"type": "email", "confidence": "medium"},
            {"type": "phone", "confidence": "high"},
        ]
        # base: 2+3=5, variety: 2 tipi * 2 = 4
        assert _compute_score(e) == 9

    def test_same_type_no_extra_bonus(self):
        e = [
            {"type": "email", "confidence": "medium"},
            {"type": "email", "confidence": "medium"},
        ]
        # base: 2+2=4, variety: 1 tipo * 2 = 2
        assert _compute_score(e) == 6

    def test_missing_confidence_defaults_medium(self):
        e = [{"type": "domain"}]
        assert _compute_score(e) == 2 + 2


# ─────────────────────────────────────────────────────────────
# _render_kept_toggle
# ─────────────────────────────────────────────────────────────

class TestRenderKeptToggle:
    def test_draft_state_shows_zero(self):
        html = _render_kept_toggle(42, False)
        assert 'id="kept-toggle-42"' in html
        assert 'value="1"' in html  # cliccando si imposta kept=1

    def test_kept_state_shows_one(self):
        html = _render_kept_toggle(42, True)
        assert 'value="0"' in html  # cliccando si toglie kept

    def test_kept_active_class_when_kept(self):
        html = _render_kept_toggle(42, True)
        assert "kept-active" in html

    def test_no_kept_active_class_when_draft(self):
        html = _render_kept_toggle(42, False)
        assert "kept-active" not in html

    def test_post_url_correct(self):
        html = _render_kept_toggle(99, False)
        assert 'hx-post="/e/99/keep"' in html


# ─────────────────────────────────────────────────────────────
# _build_markdown
# ─────────────────────────────────────────────────────────────

class TestBuildMarkdown:
    def _obs(self, entities=None, kept=False):
        return {
            "id": 7,
            "timestamp": "2026-05-05T10:00:00",
            "raw_input": "test input",
            "entities": entities or [],
            "kept": kept,
        }

    def test_header_contains_id(self):
        md = _build_markdown(self._obs())
        assert "# POE — Osservazione #7" in md

    def test_contains_timestamp(self):
        md = _build_markdown(self._obs())
        assert "2026-05-05T10:00:00" in md

    def test_contains_raw_input(self):
        md = _build_markdown(self._obs())
        assert "test input" in md

    def test_kept_state_shown(self):
        md = _build_markdown(self._obs(kept=True))
        assert "kept" in md
        md2 = _build_markdown(self._obs(kept=False))
        assert "draft" in md2

    def test_entities_grouped(self):
        entities = [
            {"type": "email", "value": "a@b.com", "original": "a@b.com",
             "confidence": "medium", "metadata": {}},
        ]
        md = _build_markdown(self._obs(entities=entities))
        assert "### email" in md
        assert "a@b.com" in md

    def test_high_confidence_annotated(self):
        entities = [
            {"type": "phone", "value": "+391234567890", "original": "+391234567890",
             "confidence": "high", "metadata": {}},
        ]
        md = _build_markdown(self._obs(entities=entities))
        assert "[high]" in md

    def test_medium_confidence_not_annotated(self):
        entities = [
            {"type": "email", "value": "a@b.com", "original": "a@b.com",
             "confidence": "medium", "metadata": {}},
        ]
        md = _build_markdown(self._obs(entities=entities))
        assert "[medium]" not in md

    def test_score_in_markdown(self):
        entities = [
            {"type": "email", "value": "a@b.com", "original": "a@b.com",
             "confidence": "medium", "metadata": {}},
        ]
        md = _build_markdown(self._obs(entities=entities))
        assert "Score:" in md


# ─────────────────────────────────────────────────────────────
# Route tests: POST /e/{id}/keep, GET /e/{id}/export.md, GET /
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_routes.db"
    monkeypatch.setattr(storage, "DB_PATH", db_file)
    storage.init_db()
    return db_file


@pytest.fixture
def test_client(temp_db, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.extractors.regex_extractor import RegexExtractor

    class _FakeRecognizer:
        def recognize(self, text: str):
            return RegexExtractor().extract(text)

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.recognizer = _FakeRecognizer()
        yield client


class TestAnalyzeRoute:
    def test_analyze_rejects_oversized_input(self, test_client, temp_db):
        resp = test_client.post("/analyze", data={"text": "x" * 50_001})
        assert resp.status_code == 400


class TestKeptRoute:
    def _create_obs(self):
        return storage.save_observation("test testo", [])

    def test_toggle_kept_true(self, test_client, temp_db):
        obs_id = self._create_obs()
        r = test_client.post(f"/e/{obs_id}/keep", data={"kept": "1"})
        assert r.status_code == 200
        assert "kept-active" in r.text
        obs = storage.get_by_id(obs_id)
        assert obs["kept"] is True

    def test_toggle_kept_false(self, test_client, temp_db):
        obs_id = self._create_obs()
        storage.set_kept(obs_id, True)
        r = test_client.post(f"/e/{obs_id}/keep", data={"kept": "0"})
        assert r.status_code == 200
        assert "kept-active" not in r.text
        obs = storage.get_by_id(obs_id)
        assert obs["kept"] is False

    def test_kept_toggle_htmx_target_in_response(self, test_client, temp_db):
        obs_id = self._create_obs()
        r = test_client.post(f"/e/{obs_id}/keep", data={"kept": "1"})
        assert f'id="kept-toggle-{obs_id}"' in r.text

    def test_toggle_nonexistent_returns_404(self, test_client, temp_db):
        r = test_client.post("/e/99999/keep", data={"kept": "1"})
        assert r.status_code == 404


class TestExportMarkdown:
    def test_export_returns_200(self, test_client, temp_db):
        obs_id = storage.save_observation("email: a@b.com", [])
        r = test_client.get(f"/e/{obs_id}/export.md")
        assert r.status_code == 200

    def test_export_content_type(self, test_client, temp_db):
        obs_id = storage.save_observation("test", [])
        r = test_client.get(f"/e/{obs_id}/export.md")
        assert "text/plain" in r.headers["content-type"]

    def test_export_filename_header(self, test_client, temp_db):
        obs_id = storage.save_observation("test", [])
        r = test_client.get(f"/e/{obs_id}/export.md")
        assert f"poe-{obs_id}.md" in r.headers.get("content-disposition", "")

    def test_export_contains_obs_id(self, test_client, temp_db):
        obs_id = storage.save_observation("testo di prova", [])
        r = test_client.get(f"/e/{obs_id}/export.md")
        assert f"#{obs_id}" in r.text

    def test_export_nonexistent_obs(self, test_client, temp_db):
        r = test_client.get("/e/99999/export.md")
        assert r.status_code == 404


class TestDeleteObservation:
    def test_delete_removes_obs(self, test_client, temp_db):
        obs_id = storage.save_observation("da eliminare", [])
        r = test_client.delete(f"/e/{obs_id}")
        assert r.status_code == 200
        assert storage.get_by_id(obs_id) is None

    def test_delete_nonexistent_returns_404(self, test_client, temp_db):
        r = test_client.delete("/e/99999")
        assert r.status_code == 404

    def test_delete_response_contains_oob_history(self, test_client, temp_db):
        obs_id = storage.save_observation("test", [])
        r = test_client.delete(f"/e/{obs_id}")
        assert 'id="history"' in r.text

    def test_delete_obs_not_in_recent_after(self, test_client, temp_db):
        obs_id = storage.save_observation("da eliminare", [])
        test_client.delete(f"/e/{obs_id}")
        recent = storage.get_recent(limit=10)
        assert all(row["id"] != obs_id for row in recent)


class TestIndexFilter:
    def test_view_all(self, test_client, temp_db):
        r = test_client.get("/?view=all")
        assert r.status_code == 200

    def test_view_kept(self, test_client, temp_db):
        r = test_client.get("/?view=kept")
        assert r.status_code == 200

    def test_view_draft(self, test_client, temp_db):
        r = test_client.get("/?view=draft")
        assert r.status_code == 200

    def test_invalid_view_defaults_all(self, test_client, temp_db):
        r = test_client.get("/?view=invalid")
        assert r.status_code == 200

    def test_filter_tabs_rendered(self, test_client, temp_db):
        r = test_client.get("/")
        assert "filter-tab" in r.text


class TestStorageNewFunctions:
    def test_set_label_saves(self, temp_db):
        obs_id = storage.save_observation("test", [])
        storage.set_label(obs_id, "Indagine Mario")
        obs = storage.get_by_id(obs_id)
        assert obs["label"] == "Indagine Mario"

    def test_set_label_none_clears(self, temp_db):
        obs_id = storage.save_observation("test", [])
        storage.set_label(obs_id, "nome")
        storage.set_label(obs_id, "")
        obs = storage.get_by_id(obs_id)
        assert obs["label"] is None

    def test_label_in_recent(self, temp_db):
        obs_id = storage.save_observation("test", [])
        storage.set_label(obs_id, "Mia etichetta")
        recent = storage.get_recent(limit=5)
        match = next(r for r in recent if r["id"] == obs_id)
        assert match["label"] == "Mia etichetta"

    def test_remove_entity_removes_one(self, temp_db):
        from app.models import Entity
        entities = [
            Entity("email", "a@b.com"),
            Entity("email", "x@y.com"),
        ]
        obs_id = storage.save_observation("test", entities)
        storage.remove_entity(obs_id, "email", "a@b.com")
        obs = storage.get_by_id(obs_id)
        values = [e["value"] for e in obs["entities"]]
        assert "a@b.com" not in values
        assert "x@y.com" in values

    def test_remove_entity_nonexistent_is_safe(self, temp_db):
        obs_id = storage.save_observation("test", [])
        storage.remove_entity(obs_id, "email", "nobody@nowhere.com")
        obs = storage.get_by_id(obs_id)
        assert obs is not None


class TestPhoneRegion:
    def test_italian_phone_has_region(self, regex_extractor):
        e = regex_extractor.extract("+39 347 1234567")
        phones = [x for x in e if x.type == "phone"]
        assert len(phones) == 1
        assert phones[0].metadata.get("region") == "IT"

    def test_uk_phone_has_region(self, regex_extractor):
        e = regex_extractor.extract("+44 20 7946 0958")
        phones = [x for x in e if x.type == "phone"]
        assert len(phones) == 1
        assert phones[0].metadata.get("region") == "GB"


class TestLabelRoute:
    def test_set_label_via_route(self, test_client, temp_db):
        obs_id = storage.save_observation("test", [])
        r = test_client.post(f"/e/{obs_id}/label", data={"label": "Test label"})
        assert r.status_code == 200
        assert "Test label" in r.text
        assert storage.get_by_id(obs_id)["label"] == "Test label"

    def test_clear_label_via_route(self, test_client, temp_db):
        obs_id = storage.save_observation("test", [])
        storage.set_label(obs_id, "Vecchio nome")
        r = test_client.post(f"/e/{obs_id}/label", data={"label": ""})
        assert r.status_code == 200
        assert storage.get_by_id(obs_id)["label"] is None


class TestRemoveEntityRoute:
    def test_remove_entity_via_route(self, test_client, temp_db):
        from app.models import Entity
        obs_id = storage.save_observation("test", [Entity("email", "a@b.com")])
        r = test_client.post(
            f"/e/{obs_id}/remove-entity",
            data={"entity_type": "email", "entity_value": "a@b.com"},
        )
        assert r.status_code == 200
        obs = storage.get_by_id(obs_id)
        assert all(e["value"] != "a@b.com" for e in obs["entities"])

    def test_accuracy_in_detail_context(self, test_client, temp_db):
        obs_id = storage.save_observation("test", [])
        r = test_client.get(f"/e/{obs_id}")
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────
# M1 — Deobfuscazione preserva confidence/metadata (regression)
# ─────────────────────────────────────────────────────────────

class TestDeobfuscationPreservesMetadata:
    def test_suspicious_tld_flag_survives_defang(self):
        from app.recognizer import Recognizer
        from app.extractors.regex_extractor import RegexExtractor

        class _NoopSpacy:
            def extract(self, text): return []

        rec = Recognizer(RegexExtractor(), _NoopSpacy())
        # Defang notation: evil[.]xyz → evil.xyz
        entities = rec.recognize("Visita evil[.]xyz per dettagli")
        domains = [e for e in entities if e.type == "domain"]
        assert len(domains) == 1
        assert domains[0].metadata.get("suspicious_tld") is True
        assert domains[0].original == "evil[.]xyz"
        assert domains[0].value == "evil.xyz"

    def test_high_confidence_survives_deobfuscation(self):
        # Email con (at) defang preserva confidence='medium' (default email)
        # ma prima del fix avrebbe perso confidence anche se passava da Entity
        # default. Test che la copia esplicita funziona.
        from app.recognizer import Recognizer
        from app.extractors.regex_extractor import RegexExtractor

        class _NoopSpacy:
            def extract(self, text): return []

        rec = Recognizer(RegexExtractor(), _NoopSpacy())
        entities = rec.recognize("Contatto: user(at)example.com")
        emails = [e for e in entities if e.type == "email"]
        assert len(emails) == 1
        assert emails[0].confidence == "medium"
        assert emails[0].original == "user(at)example.com"


# ─────────────────────────────────────────────────────────────
# M2 — _compute_accuracy helper
# ─────────────────────────────────────────────────────────────

class TestComputeAccuracy:
    def test_empty_returns_zero(self):
        from app.scoring import compute_accuracy as _compute_accuracy
        assert _compute_accuracy([]) == 0

    def test_single_high_returns_90(self):
        from app.scoring import compute_accuracy as _compute_accuracy
        assert _compute_accuracy([{"type": "phone", "confidence": "high"}]) == 90

    def test_single_medium_returns_65(self):
        from app.scoring import compute_accuracy as _compute_accuracy
        assert _compute_accuracy([{"type": "email", "confidence": "medium"}]) == 65

    def test_single_low_returns_35(self):
        from app.scoring import compute_accuracy as _compute_accuracy
        assert _compute_accuracy([{"type": "username", "confidence": "low"}]) == 35

    def test_mixed_confidence_average(self):
        from app.scoring import compute_accuracy as _compute_accuracy
        # high(90) + medium(65) + low(35) = 190 / 3 = 63.33 → round 63
        e = [
            {"type": "phone", "confidence": "high"},
            {"type": "email", "confidence": "medium"},
            {"type": "username", "confidence": "low"},
        ]
        assert _compute_accuracy(e) == 63

    def test_missing_confidence_defaults_medium(self):
        from app.scoring import compute_accuracy as _compute_accuracy
        assert _compute_accuracy([{"type": "domain"}]) == 65


# ─────────────────────────────────────────────────────────────
# M3 — Region helpers (flag + label)
# ─────────────────────────────────────────────────────────────

class TestRegionHelpers:
    def test_italy_flag(self):
        from app.main import _region_to_flag
        assert _region_to_flag("IT") == "🇮🇹"

    def test_uk_flag(self):
        from app.main import _region_to_flag
        assert _region_to_flag("GB") == "🇬🇧"

    def test_us_flag(self):
        from app.main import _region_to_flag
        assert _region_to_flag("US") == "🇺🇸"

    def test_empty_region_returns_empty(self):
        from app.main import _region_to_flag
        assert _region_to_flag("") == ""

    def test_invalid_region_length_returns_empty(self):
        from app.main import _region_to_flag
        assert _region_to_flag("ITA") == ""

    def test_lowercase_normalized(self):
        from app.main import _region_to_flag
        assert _region_to_flag("it") == "🇮🇹"

    def test_label_includes_country_name(self):
        from app.main import _region_to_label
        result = _region_to_label("IT")
        assert "🇮🇹" in result
        assert "Italia" in result

    def test_unknown_region_falls_back_to_code(self):
        from app.main import _region_to_label
        # Region che non è in _REGION_NAMES dict
        result = _region_to_label("ZZ")
        # Almeno include il codice, anche senza nome friendly
        assert "ZZ" in result or "🇿🇿" in result


# ─────────────────────────────────────────────────────────────
# M4 — Stored XSS via label (regression)
# ─────────────────────────────────────────────────────────────

class TestLabelXSS:
    def test_script_tag_in_label_escaped_in_response(self, test_client, temp_db):
        obs_id = storage.save_observation("test", [])
        payload = "<script>alert(1)</script>"
        r = test_client.post(f"/e/{obs_id}/label", data={"label": payload})
        assert r.status_code == 200
        # Il payload non deve apparire raw nell'HTML di risposta
        assert "<script>" not in r.text
        # Deve essere escaped
        assert "&lt;script&gt;" in r.text

    def test_quote_in_label_escaped_in_attribute(self, test_client, temp_db):
        obs_id = storage.save_observation("test", [])
        payload = 'breaking" onclick="alert(1)'
        r = test_client.post(f"/e/{obs_id}/label", data={"label": payload})
        assert r.status_code == 200
        # La quote non deve uscire dal value attribute
        assert 'onclick="alert(1)' not in r.text
        # Deve essere escaped
        assert "&quot;" in r.text or "&#x27;" in r.text or "&#34;" in r.text

    def test_html_entities_in_label_preserved_as_text(self, test_client, temp_db):
        obs_id = storage.save_observation("test", [])
        payload = "Indagine <Mario>"
        r = test_client.post(f"/e/{obs_id}/label", data={"label": payload})
        assert r.status_code == 200
        assert "<Mario>" not in r.text
        assert "&lt;Mario&gt;" in r.text


# ─────────────────────────────────────────────────────────────
# birth_date: validazione semantica (data 99/99/9999 deve essere scartata)
# ─────────────────────────────────────────────────────────────

class TestBirthDateValidation:
    def test_invalid_day_rejected(self, regex_extractor):
        e = regex_extractor.extract("nato il 99/01/1985")
        assert all(x.type != "birth_date" for x in e)

    def test_invalid_month_rejected(self, regex_extractor):
        e = regex_extractor.extract("nato il 15/99/1985")
        assert all(x.type != "birth_date" for x in e)

    def test_zero_day_rejected(self, regex_extractor):
        e = regex_extractor.extract("nato il 00/01/1985")
        assert all(x.type != "birth_date" for x in e)

    def test_valid_edge_31_12(self, regex_extractor):
        e = regex_extractor.extract("nato il 31/12/1985")
        dates = [x for x in e if x.type == "birth_date"]
        assert "31/12/1985" in {d.value for d in dates}


# ─────────────────────────────────────────────────────────────
# Security Headers (Task 8a)
# ─────────────────────────────────────────────────────────────

class TestSecurityHeaders:
    def test_security_headers_on_index(self, test_client, temp_db):
        resp = test_client.get("/")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "no-referrer"
        assert "default-src 'self'" in resp.headers.get("content-security-policy", "")

    def test_security_headers_on_health(self, test_client, temp_db):
        resp = test_client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
