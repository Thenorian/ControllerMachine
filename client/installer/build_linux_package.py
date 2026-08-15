"""
Monta o pacote de instalação Linux (.tar.gz) do Controller Machine — não
compila nada (Linux roda o código Python direto, sem PyInstaller), só reúne
os arquivos necessários pro serviço headless (sem gui/, que é só usado pelo
Windows) junto do install.sh numa pasta app/, e tar.gz's o resultado.

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
]
INCLUDE_DIRS = ["devices"]

# discovery.py, gui/ e assets/ não entram — só servem pra tray/janela do
# Windows, e o Linux não tem GUI (README já documenta isso). Por causa disso
# pystray/Pillow/pycups de requirements-client.txt também ficam de fora:
# nenhum módulo do pacote Linux importa eles, e pycups em especial exige
# libcups2-dev instalado no sistema só pra compilar — dependência real que
# não serve pra nada aqui, então nem vale arriscar a instalação por causa
# dela. pyserial é a única lib externa de fato usada (balança serial).
LINUX_REQUIREMENTS_HEADER = "# gerado por installer/build_linux_package.py — só o que o client Linux usa de fato\n"


def _linux_requirements() -> str:
    lines = (CLIENT_DIR / "requirements-client.txt").read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip().startswith("pyserial")]
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

    DIST_DIR.mkdir(exist_ok=True)
    tarball_path = DIST_DIR / "ControllerMachine-linux.tar.gz"
    with tarfile.open(tarball_path, "w:gz") as tar:
        tar.add(staging, arcname="ControllerMachine")

    shutil.rmtree(staging)
    print(f"Pacote gerado em {tarball_path}")
    return tarball_path


if __name__ == "__main__":
    build()
