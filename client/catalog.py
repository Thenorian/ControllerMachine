"""
Catálogo local de dispositivos. Regra central deste módulo: só o Controller
Machine cria device_id — nunca o Simple ERP. Isso garante que, mesmo com
várias lojas se cadastrando ao mesmo tempo sem coordenação nenhuma com o
servidor central, os IDs nunca colidem (uuid4 já garante isso na prática) e
que o Simple ERP nunca "inventa" um ID pra um dispositivo que não existe de
verdade na rede do cliente.

O Simple ERP pode (e deve) deixar o usuário renomear/mover um dispositivo
(mudar label, mudar de setor/fila/o-que-for dentro do ERP) — isso tudo é
gerenciado pelo lado do Simple ERP, na tabela dele. O device_id em si nunca
muda: ele é a chave que amarra "essa entrada aqui" ao periférico físico real,
para sempre.
"""
from __future__ import annotations

import uuid
from typing import Any

from config import load_config, save_config

VALID_TYPES = {"printer_common", "printer_fiscal", "scale"}


class DeviceCatalog:
    def __init__(self, config_path=None):
        self._config_path = config_path
        self._config = load_config(config_path)

    # ------------------------------------------------------------------ #

    @property
    def controller_id(self) -> str:
        return self._config["controller_id"]

    @property
    def secret(self) -> str:
        return self._config["secret"]

    @property
    def company_name(self) -> str:
        return self._config.get("company_name", "")

    @property
    def connector_host(self) -> str:
        return self._config["connector_host"]

    @property
    def connector_port(self) -> int:
        return self._config["connector_port"]

    def set_connector(self, host: str, port: int) -> None:
        """Aponta o Controller Machine pra outro servidor (endereço do
        connector embutido no Simple ERP). Quem chama isso ainda precisa
        avisar o transport pra reconectar de fato — ver
        ControllerTransport.point_to / força reconexão."""
        self._config["connector_host"] = host
        self._config["connector_port"] = port
        self._save()

    def list_devices(self) -> list[dict]:
        return list(self._config["devices"])

    def get_device(self, device_id: str) -> dict | None:
        for device in self._config["devices"]:
            if device["device_id"] == device_id:
                return device
        return None

    # ------------------------------------------------------------------ #

    def add_device(self, label: str, type_: str, brand: str, connection: dict[str, Any],
                    settings: dict[str, Any] | None = None) -> str:
        """Cadastra um dispositivo novo e devolve o device_id recém-criado
        (uuid4, mintado agora, nunca mais reaproveitado nem regenerado).

        `settings` é onde entra config específica de impressão (modo
        escpos/raw, largura de papel) — ver devices/printer_common.py e
        devices/escpos.py. Balança não usa settings, só connection+brand
        (brand escolhe o formatter, ver devices/scale/base.py)."""
        if type_ not in VALID_TYPES:
            raise ValueError(f"type inválido: {type_!r} (esperado um de {VALID_TYPES})")

        device_id = str(uuid.uuid4())
        self._config["devices"].append({
            "device_id": device_id,
            "label": label,
            "type": type_,
            "brand": brand,
            "connection": connection,
            "settings": settings or {},
        })
        self._save()
        return device_id

    def update_device(self, device_id: str, label: str, type_: str, brand: str,
                       connection: dict[str, Any], settings: dict[str, Any] | None = None) -> None:
        """Edição completa — troca label/tipo/marca/conexão/settings do
        device já cadastrado. device_id nunca muda (é a chave que amarra ao
        periférico físico real, ver docstring do módulo)."""
        if type_ not in VALID_TYPES:
            raise ValueError(f"type inválido: {type_!r} (esperado um de {VALID_TYPES})")

        device = self.get_device(device_id)
        if device is None:
            raise KeyError(device_id)
        device["label"] = label
        device["type"] = type_
        device["brand"] = brand
        device["connection"] = connection
        device["settings"] = settings or {}
        self._save()

    def rename_device(self, device_id: str, new_label: str) -> None:
        """Só o label é editável localmente — o device_id nunca muda. (O
        Simple ERP tem o próprio label editável do lado dele; este aqui é só
        o nome que aparece na interface local do Controller Machine.)"""
        device = self.get_device(device_id)
        if device is None:
            raise KeyError(device_id)
        device["label"] = new_label
        self._save()

    def remove_device(self, device_id: str) -> None:
        """Remove do catálogo local — usar só quando o periférico físico foi
        removido de verdade da loja. O Simple ERP fica sabendo porque esse
        device some do próximo `device_catalog` anunciado (ver transport.py)."""
        self._config["devices"] = [d for d in self._config["devices"] if d["device_id"] != device_id]
        self._save()

    def set_company_name(self, company_name: str) -> None:
        self._config["company_name"] = company_name
        self._save()

    # ------------------------------------------------------------------ #

    def to_announce_payload(self) -> dict[str, dict]:
        """Formato enviado no `register`/`device_catalog` pro connector:
        {device_id: {label, type, brand}} — sem os dados de conexão (IP
        interno, caminho serial etc.), que não interessam ao Simple ERP."""
        return {
            d["device_id"]: {"label": d["label"], "type": d["type"], "brand": d["brand"]}
            for d in self._config["devices"]
        }

    def _save(self) -> None:
        save_config(self._config, self._config_path)
