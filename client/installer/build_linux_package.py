"""
Monta o pacote de instalação Linux (.tar.gz) do Controller Machine — não
compila nada (Linux roda o código Python direto, sem PyInstaller), só reúne
os arquivos necessários (serviço + janela opcional, ver main.py::run_linux/
run_linux_gui) junto do install.sh numa pasta app/, e tar.gz's o resultado.

Uso: python installer/build_linux_package.py
Saída: dist/ControllerMachine-linux.tar.gz (mesma pasta dist/ do .exe).
"""
from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

CLIENT_DIR = Path(__file__).resolve().parent.parent
INSTALLER_DIR = Path(__file__).resolve().parent
DIST_DIR = CLIENT_DIR / "dist"

INCLUDE_FILES = [
    "main.py",
    "config.py",
    "catalog.py",
    "transport.py",
    "service_linux.py",
    "logging_setup.py",
    "version.py",
    "updater.py",
    "discovery.py",
    "ipc.py",
    "ipc_server.py",
    "ipc_client.py",
    "print_history.py",
]
INCLUDE_DIRS = ["devices", "gui", "assets"]

# pystray fica de fora (tray é coisa do ícone de bandeja do Windows, ver
# gui/tray.py - Linux não tem bandeja aqui, o app gráfico abre como janela
# comum do KDE/GNOME/etc, ver run_linux_gui em main.py). Pillow (ícone da
# janela) e pycups (listar impressora instalada no CUPS, ver discovery.py)
# agora entram - são usados de verdade pela janela/diálogo de dispositivo.
# pycups precisa de cabeçalho de desenvolvimento do CUPS instalado no
# sistema pra compilar (libcups2-dev no Debian/Ubuntu, cups no Arch) -
# ver aviso em installer/linux/install.sh.
LINUX_REQUIREMENTS_HEADER = "# gerado por installer/build_linux_package.py — só o que o client Linux usa de fato\n"
_LINUX_REQUIREMENTS_PREFIXOS = ("pyserial", "Pillow", "pycups", "certifi")


def _linux_requirements() -> str:
    lines = (CLIENT_DIR / "requirements-client.txt").read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.split("==")[0].split(">=")[0].strip() in _LINUX_REQUIREMENTS_PREFIXOS]
    return LINUX_REQUIREMENTS_HEADER + "\n".join(kept) + "\n"


def build() -> Path:
    staging = DIST_DIR / "_linux_package_staging"
    if staging.exists():
        shutil.rmtree(staging)
    app_dir = staging / "app"
    app_dir.mkdir(parents=True)

    for name in INCLUDE_FILES:
        shutil.copy2(CLIENT_DIR / name, app_dir / name)
    for name in INCLUDE_DIRS:
        shutil.copytree(
            CLIENT_DIR / name, app_dir / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    (app_dir / "requirements-client.txt").write_text(_linux_requirements(), encoding="utf-8")

    install_sh = staging / "install.sh"
    shutil.copy2(INSTALLER_DIR / "linux" / "install.sh", install_sh)
    install_sh.chmod(0o755)

    # install.sh substitui {venv_python}/{main_py}/{icon_path} pelo caminho
    # de instalação escolhido (só se sabe em tempo de instalação) e copia
    # pro menu de aplicativos do usuário (~/.local/share/applications) -
    # mesmo arquivo funciona em qualquer ambiente freedesktop (KDE, GNOME,
    # XFCE etc.), não precisa de nada específico de distro.
    shutil.copy2(
        INSTALLER_DIR / "linux" / "controller-machine.desktop.template",
        staging / "controller-machine.desktop.template",
    )

    DIST_DIR.mkdir(exist_ok=True)
    tarball_path = DIST_DIR / "ControllerMachine-linux.tar.gz"
    with tarfile.open(tarball_path, "w:gz") as tar:
        tar.add(staging, arcname="ControllerMachine")

    shutil.rmtree(staging)
    print(f"Pacote gerado em {tarball_path}")
    return tarball_path


if __name__ == "__main__":
    build()
