"""
Histórico local de impressão — grava cada job de impressão executado
(sucesso ou falha) num SQLite local (stdlib, sem dependência nova), pra dar
visibilidade de "o que já foi impresso" numa aba da janela principal (ver
gui/window.py). Nunca guarda o conteúdo impresso inteiro — só metadado
(quando, em qual dispositivo, que tipo de job/documento, se deu certo e a
mensagem de erro quando falhou). Fica ao lado do próprio programa, mesma
pasta dos logs (ver logging_setup.py::app_dir).
"""
from __future__ import annotations

import sqlite3
import time

from logging_setup import app_dir

_DB_PATH = app_dir() / "print_history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS impressoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    device_id TEXT NOT NULL,
    device_label TEXT NOT NULL,
    tipo_job TEXT NOT NULL,
    tipo_documento TEXT,
    sucesso INTEGER NOT NULL,
    mensagem TEXT
)
"""

# Histórico é pra consulta rápida do que aconteceu recentemente, não
# auditoria eterna — teto evita que o arquivo cresça sem limite num
# equipamento que fica ligado meses sem manutenção.
_MAX_REGISTROS = 5000


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(_SCHEMA)
    return conn


def registrar(device_id: str, device_label: str, tipo_job: str,
              tipo_documento: str | None, sucesso: bool, mensagem: str = "") -> None:
    """Nunca lança — histórico é conveniência; uma falha ao gravar aqui não
    pode derrubar (nem mascarar o resultado de) a impressão que acabou de
    ser executada de verdade."""
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO impressoes "
                "(timestamp, device_id, device_label, tipo_job, tipo_documento, sucesso, mensagem) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), device_id, device_label, tipo_job, tipo_documento,
                 int(sucesso), (mensagem or "")[:500]),
            )
            conn.execute(
                "DELETE FROM impressoes WHERE id NOT IN "
                "(SELECT id FROM impressoes ORDER BY id DESC LIMIT ?)",
                (_MAX_REGISTROS,),
            )
    except Exception:
        pass


def listar(limite: int = 200) -> list[dict]:
    """Mais recente primeiro — é assim que a aba de histórico exibe."""
    try:
        with _connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM impressoes ORDER BY id DESC LIMIT ?", (limite,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []
