"""Entry point stdio: `python -m poe_mcp` (usato da `claude mcp add`).

Avvia il server FastMCP sul trasporto stdio. Da eseguire con cwd = POE-OSINT/ e
il .venv del modulo, così che sia `poe_mcp` sia `app` siano importabili.
"""
from poe_mcp.server import build_server


def main() -> None:
    build_server().run()  # trasporto stdio di default


if __name__ == "__main__":
    main()
