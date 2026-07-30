"""
Config do Controller Machine — mesmo schema de arquivo no Windows e no Linux
(ver README.md da pasta client/ pra descrição campo a campo, isso também vai
pra Wiki do Obsidian).

Regra importante (não é só estilo, é contrato com o Simple ERP): `controller_id`
e o `device_id` de cada dispositivo são gerados **uma única vez, localmente,
neste arquivo** — nunca pelo Simple ERP, nunca pelo connector. Depois de
criado, o ID nunca muda, mesmo que o dispositivo seja renomeado ou realocado
pra outra fila/setor dentro do Simple ERP. Ver catalog.py para a mintagem.
"""
from __future__ import annotations

import json
import os
import platform
import uuid
from pathlib import Path

DEFAULT_CONNECTOR_PORT = 7689


def default_config_path() -> Path:
    """Windows: %APPDATA%\\ControllerMachine\\config.json
    Linux: /etc/controller-machine/config.json (systemd roda como root e lê
    de um caminho fixo do sistema) — com fallback pro diretório do usuário se
    não tiver permissão de escrita em /etc (ex.: rodando sem sudo, modo teste)."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "ControllerMachine" / "config.json"

    system_path = Path("/etc/controller-machine/config.json")
    if system_path.parent.exists() and os.access(system_path.parent, os.W_OK):
        return system_path
    return Path.home() / ".config" / "controller-machine" / "config.json"


def default_config() -> dict:
    return {
        "connector_host": "127.0.0.1",
        "connector_port": DEFAULT_CONNECTOR_PORT,
        "controller_id": str(uuid.uuid4()),
        "secret": str(uuid.uuid4()),
        "company_name": "",
        "devices": [],
    }


def load_config(path: Path | None = None) -> dict:
    path = path or default_config_path()
    if not path.exists():
        config = default_config()
        save_config(config, path)
        return config

    with path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    # Preenche campos que possam faltar (upgrade de config antiga) sem nunca
    # sobrescrever um controller_id/device_id já existente.
    changed = False
    for key, value in default_config().items():
        if key not in config:
            config[key] = value
            changed = True
    if changed:
        save_config(config, path)

    return config


def save_config(config: dict, path: Path | None = None) -> None:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
