"""
Impressão comum (não fiscal) — raw, PDF, ou direto num endereço de rede
(porta 9100, padrão "impressora de rede crua" que a maioria dos equipamentos
ESC/POS aceita mesmo sem estar instalada como fila no SO).
"""
from __future__ import annotations

import logging
import os
import platform
import socket
import subprocess
import tempfile
import time

logger = logging.getLogger("printer_common")


def print_raw(connection: dict, data: bytes) -> None:
    """connection: {"kind": "os_printer", "os_name": "..."} — impressora já
    instalada no SO (Windows: win32print; Linux: CUPS via `lp -o raw`)."""
    system = platform.system()
    os_name = connection["os_name"]

    if system == "Windows":
        import win32print
        handle = win32print.OpenPrinter(os_name)
        try:
            win32print.StartDocPrinter(handle, 1, ("Controller Machine", None, "RAW"))
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, data)
            win32print.EndPagePrinter(handle)
            win32print.EndDocPrinter(handle)
        finally:
            win32print.ClosePrinter(handle)
        return

    if system == "Linux":
        # -o raw evita o CUPS tentar interpretar/reformatar o conteúdo (ESC/POS
        # não é um formato de documento normal, precisa ir cru pra impressora).
        subprocess.run(["lp", "-d", os_name, "-o", "raw"], input=data, check=True)
        return

    raise NotImplementedError(f"print_raw não implementado para {system!r}")


def print_via_tcp(connection: dict, data: bytes, timeout: float = 10) -> None:
    """connection: {"kind": "tcp", "host": "...", "port": 9100} — impressora
    de rede que não está (e não precisa estar) instalada no SO."""
    with socket.create_connection((connection["host"], connection["port"]), timeout=timeout) as sock:
        sock.sendall(data)


def print_pdf(connection: dict, data: bytes) -> None:
    """Imprime um PDF já pronto — usa o visualizador padrão do SO (Windows)
    ou `lp` (Linux), que ambos sabem renderizar PDF corretamente (diferente
    do raw, aqui QUEREMOS que o SO interprete o arquivo)."""
    system = platform.system()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        if system == "Windows":
            import win32api
            win32api.ShellExecute(0, "print", tmp_path, None, ".", 0)
            time.sleep(2)  # dá tempo do processo associado abrir o arquivo antes de apagar
        elif system == "Linux":
            os_name = connection["os_name"]
            subprocess.run(["lp", "-d", os_name, tmp_path], check=True)
        else:
            raise NotImplementedError(f"print_pdf não implementado para {system!r}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            logger.warning(f"Não foi possível remover o temporário {tmp_path}")
