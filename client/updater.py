"""
Auto-atualização do Controller Machine — verifica a API pública do GitHub
(repositório é open source, não precisa de autenticação nenhuma pra ler
releases) uma vez ao iniciar e a cada CHECK_INTERVAL_SECONDS depois disso
(ver chamada em main.py::run_linux/run_windows). Quando existe uma release
mais nova que a instalada (version.py), baixa o pacote certo pra
plataforma atual, instala por cima da instalação existente e reinicia
sozinho - sem intervenção do operador da loja.

Só roda de verdade quando a instalação é "real" (ver
_rodando_de_instalacao_real) - nunca em cima do worktree de quem está
desenvolvendo (senão um `git status` viraria uma bagunça de arquivo
baixado por cima de arquivo versionado).

Erro em qualquer etapa (sem internet, GitHub fora do ar, release sem o
asset esperado, etc.) só loga e devolve False - nunca derruba o processo
principal por causa disso, ele continua rodando normalmente na versão
atual até a próxima checagem.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from version import __version__

logger = logging.getLogger("updater")

REPO = "Thenorian/ControllerMachine"
RELEASES_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_INTERVAL_SECONDS = 3600

_ASSET_LINUX = "ControllerMachine-linux.tar.gz"
_ASSET_WINDOWS = "ControllerMachine.exe"


def _parse_version(versao: str) -> tuple[int, ...]:
    """"v1.10" -> (1, 10) - comparação numérica de verdade, não string
    ("1.9" < "1.10" como string daria errado)."""
    partes = []
    for pedaco in versao.strip().lstrip("vV").split("."):
        digitos = "".join(c for c in pedaco if c.isdigit())
        partes.append(int(digitos) if digitos else 0)
    return tuple(partes) or (0,)


def _rodando_de_instalacao_real() -> bool:
    """Windows: só quando compilado (PyInstaller), nunca rodando
    `python main.py` direto em dev. Linux (nunca "frozen", roda sempre
    fonte Python puro - ver build_linux_package.py): considera instalação
    real quando NÃO existe nenhum `.git` acima deste arquivo - a pasta
    instalada (~/.thenorian/controller) só tem os arquivos copiados pelo
    install.sh, sem .git; um worktree de desenvolvimento sempre tem."""
    if getattr(sys, "frozen", False):
        return True
    if platform.system() == "Windows":
        return False
    aqui = Path(__file__).resolve()
    return not any((pai / ".git").exists() for pai in aqui.parents)


def _buscar_release_mais_recente() -> dict | None:
    req = urllib.request.Request(
        RELEASES_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ControllerMachine-updater"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as err:
        logger.warning(f"Falha consultando releases do GitHub: {err}")
        return None


def _baixar_asset(assets: list[dict], nome: str, destino: Path) -> bool:
    asset = next((a for a in assets if a.get("name") == nome), None)
    if not asset:
        logger.warning(f"Release mais recente não tem o asset '{nome}' - pulando atualização")
        return False
    try:
        req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "ControllerMachine-updater"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(destino, "wb") as f:
            shutil.copyfileobj(resp, f)
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        logger.warning(f"Falha baixando atualização: {err}")
        return False
    return destino.exists() and destino.stat().st_size > 0


def verificar_e_atualizar() -> bool:
    """Devolve True quando uma atualização foi baixada e a troca/reinício já
    foi disparada - quem chamou deve parar o que estiver fazendo e deixar
    o processo terminar (o processo novo assume a partir daí). False =
    nada a fazer (já na última versão, ou alguma etapa falhou) - continua
    rodando normalmente."""
    try:
        if not _rodando_de_instalacao_real():
            return False

        release = _buscar_release_mais_recente()
        if not release or release.get("draft") or release.get("prerelease"):
            return False

        versao_remota = release.get("tag_name", "")
        if _parse_version(versao_remota) <= _parse_version(__version__):
            return False

        logger.info(f"Nova versão disponível: {versao_remota} (atual: v{__version__}) - baixando...")
        assets = release.get("assets", [])
        tmp_dir = Path(tempfile.mkdtemp(prefix="controllermachine-update-"))

        if platform.system() == "Windows":
            return _atualizar_windows(assets, tmp_dir)
        return _atualizar_linux(assets, tmp_dir)
    except Exception:
        logger.exception("Falha inesperada verificando atualização - seguindo na versão atual")
        return False


def _atualizar_windows(assets: list[dict], tmp_dir: Path) -> bool:
    novo_exe = tmp_dir / "ControllerMachine.new.exe"
    if not _baixar_asset(assets, _ASSET_WINDOWS, novo_exe):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    # Um .exe rodando não consegue se sobrescrever no Windows (arquivo fica
    # travado) - dispara um .bat separado que espera o processo atual soltar
    # o arquivo (tentando copiar em loop), troca e relança. Mesmo truque já
    # usado em installer/windows_installer.py::schedule_self_delete - inclusive
    # o cuidado de só apagar o PRÓPRIO .bat como última linha (`del "%~f0"`),
    # nunca a pasta que ainda o contém enquanto ele está rodando (cmd.exe
    # travaria tentando remover um diretório em uso pelo processo atual).
    exe_atual = Path(sys.executable)
    bat_path = tmp_dir / "atualizar.bat"
    bat_content = (
        "@echo off\r\n"
        ":loop\r\n"
        f'copy /y "{novo_exe}" "{exe_atual}" >nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto loop\r\n"
        ")\r\n"
        f'del "{novo_exe}" >nul 2>&1\r\n'
        f'start "" "{exe_atual}"\r\n'
        'del "%~f0"\r\n'
    )
    bat_path.write_text(bat_content, encoding="utf-8")
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )
    logger.info("Atualização baixada - reiniciando em segundo plano...")
    return True


def _atualizar_linux(assets: list[dict], tmp_dir: Path) -> bool:
    tarball = tmp_dir / _ASSET_LINUX
    if not _baixar_asset(assets, _ASSET_LINUX, tarball):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    extract_dir = tmp_dir / "extraido"
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            try:
                tar.extractall(extract_dir, filter="data")  # Python 3.12+
            except TypeError:
                tar.extractall(extract_dir)  # fallback pra Python mais antigo
    except (tarfile.TarError, OSError) as err:
        logger.warning(f"Pacote de atualização corrompido: {err}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    novo_app_dir = extract_dir / "ControllerMachine" / "app"
    if not novo_app_dir.is_dir():
        logger.warning("Pacote baixado não tem o formato esperado - abortando atualização")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    # Instalado como usuário dono da instalação (~/.thenorian/controller,
    # ver install.sh) - nunca precisa de root pra sobrescrever os próprios
    # arquivos, só a instalação inicial do serviço systemd precisou de sudo.
    install_dir = Path(__file__).resolve().parent
    for item in novo_app_dir.iterdir():
        destino = install_dir / item.name
        if item.is_dir():
            shutil.rmtree(destino, ignore_errors=True)
            shutil.copytree(item, destino)
        else:
            shutil.copy2(item, destino)

    requirements = install_dir / "requirements-client.txt"
    if requirements.exists():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(requirements)],
            check=False,
        )

    shutil.rmtree(tmp_dir, ignore_errors=True)
    logger.info("Atualização instalada.")

    import service_linux
    if service_linux.is_running_under_systemd():
        # Restart=on-failure (ver service_linux.UNIT_TEMPLATE) já cuida de
        # subir de novo sozinho com o código novo - só precisa sair com
        # status de erro. os._exit pra não rodar nenhum cleanup do
        # interpretador no meio do caminho (finally de threads etc.).
        logger.info("Encerrando para o systemd reiniciar com a nova versão...")
        os._exit(1)
    else:
        # Rodando em primeiro plano (dev/teste, fora do systemd) - sobe uma
        # cópia nova detached antes de sair, senão ninguém mais reinicia.
        subprocess.Popen([sys.executable, str(install_dir / "main.py")], start_new_session=True)
        os._exit(0)
