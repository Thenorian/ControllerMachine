"""
Registro como serviço systemd no Linux — em vez de exigir que o cliente
edite um .service manualmente, `python main.py --install-service` escreve o
unit file certo e já habilita/inicia. Sem GUI/tray no Linux (systemd não tem
bandeja) — a "interface" no Linux é o config.json (mesmo schema do Windows)
mais os logs do `journalctl`.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("service_linux")

SERVICE_NAME = "controller-machine"
UNIT_PATH = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")

UNIT_TEMPLATE = """[Unit]
Description=Controller Machine — conector de impressoras e balanças
After=network-online.target cups.service
Wants=network-online.target

[Service]
Type=simple
ExecStart={python_exe} {entrypoint}
Restart=on-failure
RestartSec=5
User={user}

[Install]
WantedBy=multi-user.target
"""


def is_running_under_systemd() -> bool:
    """systemd seta essas variáveis de ambiente nos processos que ele
    gerencia — presença delas indica que já estamos rodando como serviço,
    não precisa (nem deve) tentar se reinstalar."""
    return "INVOCATION_ID" in os.environ or "JOURNAL_STREAM" in os.environ


def install_and_start(entrypoint_path: str, run_as_user: str | None = None) -> bool:
    """Devolve True se o serviço foi instalado/iniciado com sucesso. Precisa
    rodar como root (senão só imprime as instruções e devolve False, sem
    quebrar a execução — quem chamou pode continuar rodando em primeiro
    plano normalmente)."""
    if os.geteuid() != 0:
        logger.warning(
            "Instalação do serviço systemd precisa de root. Rode com sudo, ou instale "
            "manualmente copiando o unit abaixo para "
            f"{UNIT_PATH} e depois:\n"
            f"    sudo systemctl daemon-reload && sudo systemctl enable --now {SERVICE_NAME}\n\n"
            + UNIT_TEMPLATE.format(
                python_exe=sys.executable, entrypoint=entrypoint_path, user=run_as_user or "root"
            )
        )
        return False

    user = run_as_user or os.environ.get("SUDO_USER", "root")
    unit_content = UNIT_TEMPLATE.format(python_exe=sys.executable, entrypoint=entrypoint_path, user=user)
    UNIT_PATH.write_text(unit_content, encoding="utf-8")

    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", SERVICE_NAME], check=True)
    logger.info(f"Serviço {SERVICE_NAME} instalado e iniciado. Logs: journalctl -u {SERVICE_NAME} -f")
    return True


def uninstall() -> None:
    if os.geteuid() != 0:
        logger.warning("Remoção do serviço também precisa de root.")
        return
    subprocess.run(["systemctl", "disable", "--now", SERVICE_NAME], check=False)
    if UNIT_PATH.exists():
        UNIT_PATH.unlink()
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    logger.info(f"Serviço {SERVICE_NAME} removido.")
