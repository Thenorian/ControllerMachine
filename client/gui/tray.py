"""
Ícone na bandeja do Windows. Usa o ícone pixel-art gerado em
assets/generate_icon.py (em memória, não depende do .ico já existir em
disco). Se `pystray`/`Pillow` não estiverem instalados, cai pra rodar sem
bandeja (só a janela, ou nada — ver main.py).
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("tray")

try:
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False


def run_tray(window) -> None:
    """`window` é a instância de gui.window.ControllerWindow — já criada e
    rodando na thread principal do Tk. O ícone da bandeja roda numa thread
    separada e só manda comandos pra ela (abrir/esconder/sair)."""
    if not HAS_TRAY:
        logger.warning("pystray não instalado — rodando sem ícone de bandeja")
        return

    from assets.generate_icon import build_icon_image

    def on_open(icon, item):
        window.deiconify()
        window.lift()

    def on_quit(icon, item):
        icon.stop()
        window.quit()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir Controller Machine", on_open, default=True),
        pystray.MenuItem("Sair", on_quit),
    )
    icon = pystray.Icon("ControllerMachine", build_icon_image(scale=4), "Controller Machine", menu)

    threading.Thread(target=icon.run, daemon=True).start()


def install_windows_autostart(entrypoint_path: str) -> None:
    """Cria um atalho na pasta Startup do usuário atual, pra abrir junto com
    o Windows sem precisar de login manual toda vez."""
    import os
    import sys

    startup_dir = os.path.join(
        os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
    )
    shortcut_path = os.path.join(startup_dir, "Controller Machine.lnk")

    try:
        import pythoncom
        from win32com.client import Dispatch

        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.TargetPath = sys.executable
        shortcut.Arguments = f'"{entrypoint_path}"'
        shortcut.WorkingDirectory = os.path.dirname(entrypoint_path)
        shortcut.IconLocation = os.path.join(os.path.dirname(entrypoint_path), "assets", "icon.ico")
        shortcut.save()
        logger.info(f"Atalho de inicialização automática criado em {shortcut_path}")
    except ImportError:
        logger.warning(
            "pywin32 (win32com) não disponível — não foi possível criar o atalho de "
            "autostart automaticamente. Alternativa manual: copiar um atalho do "
            "programa pra essa pasta:\n" + startup_dir
        )
