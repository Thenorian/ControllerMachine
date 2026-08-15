"""
Sistema de logs do Controller Machine — grava em disco na pasta `logs/` ao
lado do próprio programa (o instalador cria essa pasta junto da instalação,
ver installer/). Rotaciona por dia (troca de arquivo à meia-noite) e nunca
deixa acumular mais que 25 arquivos — os mais antigos são apagados sozinhos
pelo próprio TimedRotatingFileHandler, sem precisar de faxina manual.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

MAX_LOG_FILES = 25


def app_dir() -> Path:
    """Diretório onde o programa está rodando de verdade — o .exe compilado
    (sys.frozen) ou este arquivo em modo dev (`python main.py`). É sempre ao
    lado dessa pasta que fica logs/, então funciona tanto instalado quanto
    em desenvolvimento."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def setup_logging(level: int = logging.INFO) -> None:
    log_dir = app_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "controller-machine.log",
        when="midnight",
        backupCount=MAX_LOG_FILES,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    handlers: list[logging.Handler] = [file_handler]

    if sys.stdout is not None:  # o .exe --windowed não tem console/stdout
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)
