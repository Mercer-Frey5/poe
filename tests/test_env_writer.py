"""env_writer.py — aggiorna .env in-place preservando commenti/ordine, per il
pannello "API" nella status bar (scrivere API key da UI invece che a mano)."""
from app.env_writer import write_env_keys


def test_updates_existing_key_preserving_comments_and_order(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# commento sopra\n"
        "ABUSEIPDB_API_KEY=old-value\n"
        "\n"
        "# commento sotto\n"
        "VIRUSTOTAL_API_KEY=\n",
        encoding="utf-8",
    )
    write_env_keys(env_path, {"ABUSEIPDB_API_KEY": "new-value"})
    content = env_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0] == "# commento sopra"
    assert lines[1] == "ABUSEIPDB_API_KEY=new-value"
    assert lines[3] == "# commento sotto"
    assert lines[4] == "VIRUSTOTAL_API_KEY="


def test_appends_key_not_already_present(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("ABUSEIPDB_API_KEY=abc\n", encoding="utf-8")
    write_env_keys(env_path, {"SHODAN_API_KEY": "xyz"})
    content = env_path.read_text(encoding="utf-8")
    assert "ABUSEIPDB_API_KEY=abc" in content
    assert "SHODAN_API_KEY=xyz" in content


def test_creates_file_if_missing(tmp_path):
    env_path = tmp_path / ".env"
    assert not env_path.exists()
    write_env_keys(env_path, {"ABUSEIPDB_API_KEY": "abc"})
    assert env_path.exists()
    assert "ABUSEIPDB_API_KEY=abc" in env_path.read_text(encoding="utf-8")


def test_updates_multiple_keys_in_one_call(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "ABUSEIPDB_API_KEY=old1\nVIRUSTOTAL_API_KEY=old2\nSHODAN_API_KEY=old3\n",
        encoding="utf-8",
    )
    write_env_keys(env_path, {"ABUSEIPDB_API_KEY": "new1", "SHODAN_API_KEY": "new3"})
    content = env_path.read_text(encoding="utf-8")
    assert "ABUSEIPDB_API_KEY=new1" in content
    assert "VIRUSTOTAL_API_KEY=old2" in content
    assert "SHODAN_API_KEY=new3" in content


def test_does_not_match_key_as_substring_of_another(tmp_path):
    """ABUSEIPDB_API_KEY non deve matchare una riga tipo
    ABUSEIPDB_API_KEY_BACKUP=... (prefix match sbagliato)."""
    env_path = tmp_path / ".env"
    env_path.write_text("ABUSEIPDB_API_KEY_BACKUP=untouched\n", encoding="utf-8")
    write_env_keys(env_path, {"ABUSEIPDB_API_KEY": "new"})
    content = env_path.read_text(encoding="utf-8")
    assert "ABUSEIPDB_API_KEY_BACKUP=untouched" in content
    assert "ABUSEIPDB_API_KEY=new" in content
