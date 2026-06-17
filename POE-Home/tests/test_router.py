from agents import router


def test_route_matches_osint_keyword():
    assert router.route("Cerca informazioni su Mario Rossi") == "osint"


def test_route_matches_diario_keyword():
    assert router.route("Appunta questa cosa nel diario") == "diario"


def test_route_matches_analisi_keyword():
    assert router.route("Fammi un'analisi dei dati") == "analisi"


def test_route_returns_none_for_generic_question():
    assert router.route("Che ore sono?") is None


def test_placeholder_response_mentions_module_name():
    out = router.placeholder_response("osint")
    assert "OSINT" in out.verbal
    assert out.visual is None


def test_route_search_words_do_not_trigger_osint():
    assert router.route("fai una ricerca su Firenze") is None
    assert router.route("cerca notizie di cybersecurity") is None


def test_route_osint_still_triggers_on_explicit_keywords():
    assert router.route("fai un osint su questo dominio") == "osint"
    assert router.route("indaga su questo indirizzo") == "osint"
