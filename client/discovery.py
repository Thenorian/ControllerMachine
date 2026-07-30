"""
Descoberta de impressoras já instaladas no SO — cobre impressora USB e de
rede, porque ambas aparecem como fila instalada no spooler do sistema
operacional (Windows) ou no CUPS (Linux). Não tenta descobrir balança
automaticamente — balança normalmente não se anuncia na rede (é serial ou
IP fixo configurado no equipamento), então esse cadastro é sempre manual
(ver gui/window.py, botão "Adicionar dispositivo manualmente").
"""
from __future__ import annotations

import logging
import platform

logger = logging.getLogger("discovery")


def discover_os_printers() -> list[str]:
    """Lista os nomes das impressoras já instaladas no SO. Devolve lista
    vazia (com aviso no log) se a lib necessária não estiver disponível —
    nunca derruba o programa por causa disso."""
    system = platform.system()
    if system == "Windows":
        return _discover_windows()
    if system == "Linux":
        return _discover_linux_cups()

    logger.warning(f"Descoberta de impressoras não implementada para {system!r}")
    return []


def _discover_windows() -> list[str]:
    try:
        import win32print
    except ImportError:
        logger.warning("pywin32 não instalado — não é possível listar impressoras do Windows")
        return []

    # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS cobre impressoras locais
    # (inclusive USB) e as conectadas via rede/servidor de impressão.
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [printer[2] for printer in win32print.EnumPrinters(flags)]


def _discover_linux_cups() -> list[str]:
    try:
        import cups
    except ImportError:
        logger.warning("pycups não instalado — não é possível listar impressoras do CUPS")
        return []

    try:
        connection = cups.Connection()
        return list(connection.getPrinters().keys())
    except Exception:
        logger.exception("Falha ao consultar o CUPS")
        return []
