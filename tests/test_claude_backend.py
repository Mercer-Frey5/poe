"""TDD ClaudeCodeBackend — Claude via abbonamento (Claude Code headless).
Nessun `claude` reale: il subprocess è mockato."""
import asyncio

import pytest

from app.llm.claude_backend import ClaudeCodeBackend


class _FakeProc:
    def __init__(self, out=b"", err=b"", rc=0):
        self._out, self._err, self.returncode = out, err, rc

    async def communicate(self):
        return self._out, self._err

    def kill(self):
        pass


def test_build_cmd_include_model_system_prompt():
    b = ClaudeCodeBackend(model="sonnet", binary="claude")
    cmd = b._build_cmd("ciao", "sii breve")
    assert cmd[:4] == ["claude", "-p", "--output-format", "json"]
    # lean: niente MCP + niente tool built-in (~6x meno token/costo)
    assert "--strict-mcp-config" in cmd
    assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == ""
    assert "--model" in cmd and "sonnet" in cmd
    assert "--append-system-prompt" in cmd and "sii breve" in cmd
    assert cmd[-1] == "ciao"   # il prompt è l'ultimo argomento


def test_parse_output_json_and_fallback():
    assert ClaudeCodeBackend._parse_output('{"result":"ok"}') == "ok"
    assert ClaudeCodeBackend._parse_output("testo grezzo") == "testo grezzo"
    assert ClaudeCodeBackend._parse_output("") == ""
    # json senza 'result' -> fallback al grezzo
    assert ClaudeCodeBackend._parse_output('{"altro":1}') == '{"altro":1}'


def test_generate_parses_result(monkeypatch):
    async def fake_exec(*a, **k):
        return _FakeProc(out=b'{"result":"Dominio sospetto: crea nel 2024."}', rc=0)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    b = ClaudeCodeBackend()
    out = asyncio.run(b.generate("prompt", "system"))
    assert out == "Dominio sospetto: crea nel 2024."


def test_generate_raises_on_error(monkeypatch):
    async def fake_exec(*a, **k):
        return _FakeProc(err=b"not authenticated", rc=1)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    b = ClaudeCodeBackend()
    with pytest.raises(RuntimeError):
        asyncio.run(b.generate("prompt"))


def test_is_available_true_on_version_ok(monkeypatch):
    async def fake_exec(*a, **k):
        return _FakeProc(out=b"1.2.3", rc=0)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert asyncio.run(ClaudeCodeBackend().is_available()) is True


def test_subscription_env_removes_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-non-usare")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    env = ClaudeCodeBackend._subscription_env()
    assert "ANTHROPIC_API_KEY" not in env      # -> abbonamento, mai API a pagamento
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_generate_passes_env_without_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-non-usare")
    captured = {}

    async def fake_exec(*a, **k):
        captured["env"] = k.get("env")
        return _FakeProc(out=b'{"result":"ok"}', rc=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    asyncio.run(ClaudeCodeBackend().generate("prompt"))
    assert captured["env"] is not None
    assert "ANTHROPIC_API_KEY" not in captured["env"]


def test_make_llm_backend_selects_claude(monkeypatch):
    monkeypatch.setenv("POE_LLM_BACKEND", "claude")
    from app.main import _make_llm_backend
    assert isinstance(_make_llm_backend(), ClaudeCodeBackend)


def test_make_llm_backend_avvisa_se_i_dati_escono(monkeypatch, caplog):
    """POE preferisce i motori locali, ma se l'unico disponibile fa uscire i
    dati (Claude, o un endpoint OpenAI-compat non locale) deve dirlo AL BOOT,
    non lasciarlo scoprire dall'utente aprendo l'interfaccia."""
    monkeypatch.setenv("POE_LLM_BACKEND", "claude")
    from app.main import _make_llm_backend
    import logging
    with caplog.at_level(logging.WARNING):
        _make_llm_backend()
    assert any("escono" in r.message or "esterno" in r.message for r in caplog.records)


def test_make_llm_backend_openai_compat_su_endpoint_pubblico_avvisa(monkeypatch, caplog):
    monkeypatch.setenv("POE_LLM_BACKEND", "openai")
    monkeypatch.setenv("POE_OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    from app.main import _make_llm_backend
    import logging
    with caplog.at_level(logging.WARNING):
        _make_llm_backend()
    assert any("escono" in r.message or "esterno" in r.message for r in caplog.records)


def test_make_llm_backend_openai_compat_locale_non_avvisa(monkeypatch, caplog):
    """LM Studio sulla stessa macchina non deve produrre un avviso di privacy:
    sarebbe un falso allarme che insegna a ignorare quelli veri."""
    monkeypatch.setenv("POE_LLM_BACKEND", "openai")
    monkeypatch.setenv("POE_OPENAI_BASE_URL", "http://localhost:1234/v1")
    from app.main import _make_llm_backend
    import logging
    with caplog.at_level(logging.WARNING):
        _make_llm_backend()
    assert not any("escono" in r.message or "esterno" in r.message for r in caplog.records)
