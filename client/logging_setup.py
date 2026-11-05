"""
Sistema de logs do Controller Machine — grava em disco na pasta `logs/` ao
lado do próprio programa (o instalador cria essa pasta junto da instalação,
ver installer/). Rotaciona por dia (troca de arquivo à meia-noite) e nunca
deixa acumular mais que 25 arquivos — os mais antigos são apagados sozinhos,
sem precisar de faxina manual. O nome do arquivo já traz a data
("controller-machine-2026-11-05.log"), pra dar pra achar o dia certo sem
abrir cada um (ver _ArquivoComDataNoNome).
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from datetime import date
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


def _nome_log_de_hoje(log_dir: Path) -> Path:
    return log_dir / f"controller-machine-{date.today():%Y-%m-%d}.log"


class _ArquivoComDataNoNome(logging.handlers.TimedRotatingFileHandler):
    """TimedRotatingFileHandler nunca renomeia o arquivo ATIVO, só os que já
    rotacionaram - o nome ficaria preso na data em que o processo subiu,
    mesmo rodando dias sem reiniciar (comum num PDV que fica ligado o mês
    inteiro). `_open` é chamado tanto na construção quanto bem no meio de
    todo rollover (depois do arquivo de ontem já ter sido movido de lado),
    então recalcular o nome aqui garante que o arquivo ativo sempre mostra
    a data de hoje de verdade.

    getFilesToDelete também precisa de override: a versão original do
    stdlib procura arquivo velho pelo nome exato do arquivo ativo atual
    (que aqui muda todo dia) - sem isso o limite de MAX_LOG_FILES para de
    funcionar a partir do segundo dia. Não usa `namer` pra "limpar" o
    sufixo de data que o rollover cola no arquivo rotacionado (ficaria
    "...log.2026-11-05") - colar por cima do nome que já tem a data faria
    o arquivo rotacionado ficar com o MESMO nome do arquivo ativo (os dois
    já têm a data de hoje embutida), e doRollover() usa isso pra detectar
    "já rotacionou" e não rotaciona de verdade. O sufixo meio redundante no
    arquivo já rotacionado não é problema - só o arquivo ativo de hoje
    precisa ficar com nome limpo."""

    def _open(self):
        self.baseFilename = str(_nome_log_de_hoje(Path(self.baseFilename).parent))
        return super()._open()

    def getFilesToDelete(self) -> list[str]:
        log_dir = Path(self.baseFilename).parent
        arquivos = sorted(log_dir.glob("controller-machine-*"))
        excedente = len(arquivos) - self.backupCount
        return [str(p) for p in arquivos[:excedente]] if excedente > 0 else []


def setup_logging(level: int = logging.INFO) -> None:
    log_dir = app_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    file_handler = _ArquivoComDataNoNome(
        _nome_log_de_hoje(log_dir),
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
