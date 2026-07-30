"""
Demonstração manual do ControllerConnector — NÃO é o módulo em si (esse é
connector.py) e não é código de produção. Serve só pra testar o socket sem
precisar ter o Simple ERP de verdade rodando ao lado.

Rodar (a partir da pasta server/):

    python example_usage.py

Isso sobe o connector na porta 7689 e cadastra um controller de teste
("11111111-1111-1111-1111-111111111111" / segredo "segredo-de-teste") — use
esses mesmos valores no config.json do client pra testar a conexão de ponta a
ponta.
"""
import logging
import sqlite3

from connector import ControllerConnector

DB_FILE = "example_controllers.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS controllers (
            controller_id TEXT PRIMARY KEY,
            company_name  TEXT NOT NULL,
            secret        TEXT NOT NULL
        )
        """
    )
    return conn


def check_auth(controller_id: str, secret: str) -> bool:
    """Isso aqui é o papel do Simple ERP: decidir se o controller_id que
    bateu na porta pertence a uma empresa com acesso ativo. No exemplo,
    é só uma tabela SQLite solta; no Simple ERP de verdade, é uma consulta
    no banco real (join com a licença/assinatura da empresa, por exemplo)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM controllers WHERE controller_id = ? AND secret = ?",
            (controller_id, secret),
        ).fetchone()
        return row is not None


def register_example_controller(controller_id: str, company_name: str, secret: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO controllers (controller_id, company_name, secret) VALUES (?, ?, ?)",
            (controller_id, company_name, secret),
        )


def on_event(event: str, payload: dict) -> None:
    logging.info(f"[evento] {event}: {payload}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    register_example_controller(
        "11111111-1111-1111-1111-111111111111",
        "Loja Teste",
        "segredo-de-teste",
    )

    connector = ControllerConnector(auth_check=check_auth, on_event=on_event)
    connector.start()

    try:
        input("Connector rodando em 0.0.0.0:7689. Pressione Enter para encerrar...\n")
    finally:
        connector.stop()
