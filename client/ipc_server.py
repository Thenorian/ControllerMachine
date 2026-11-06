"""
Lado servidor do IPC local (ver ipc.py) - roda dentro do processo do
serviço (main.py::run_linux), dono de verdade do catálogo/conexão. Só
expõe o que o app gráfico (gui_linux.py) precisa pra funcionar como
visualizador/controle remoto da mesma janela já usada no Windows
(gui/window.py) - um comando por método público de DeviceCatalog/
ControllerTransport/updater que a janela chama.
"""
from __future__ import annotations

import logging
import os
import socket
import threading

import print_history
import updater
import version
from catalog import DeviceCatalog
from ipc import SOCKET_PERMISSIONS, recv_json, send_json, socket_path
from transport import ControllerTransport

logger = logging.getLogger("ipc_server")


class IPCServer:
    def __init__(self, catalog: DeviceCatalog, transport: ControllerTransport):
        self.catalog = catalog
        self.transport = transport
        self._server_socket: socket.socket | None = None
        self._running = False
        self._accept_thread: threading.Thread | None = None

    def start(self) -> None:
        path = socket_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()  # reinício do serviço deixa o arquivo velho pra trás

        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(str(path))
        os.chmod(path, SOCKET_PERMISSIONS)
        self._server_socket.listen()
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        logger.info(f"IPC local ouvindo em {path}")

    def stop(self) -> None:
        self._running = False
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._server_socket.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn: socket.socket) -> None:
        buffer = b""
        try:
            while self._running:
                buffer, msg = recv_json(conn, buffer)
                if msg is None:
                    break
                if msg:
                    send_json(conn, self._dispatch(msg))
        except (OSError, ValueError) as err:
            logger.warning(f"Erro na conexão IPC: {err}")
        finally:
            conn.close()

    def _dispatch(self, msg: dict) -> dict:
        comando = msg.get("comando")
        handler = _COMANDOS.get(comando)
        if handler is None:
            return {"status": "error", "message": f"comando desconhecido: {comando!r}"}
        try:
            resultado = handler(self, msg.get("params") or {})
            return {"status": "ok", "resultado": resultado}
        except Exception as err:
            logger.exception(f"Falha executando comando IPC {comando!r}")
            return {"status": "error", "message": str(err)}

    # ------------------------------------------------------------------ #
    # Comandos - cada um espelha um método já existente de catalog/
    # transport/updater/print_history, sem adicionar lógica nova aqui.
    # ------------------------------------------------------------------ #

    def _get_identity(self, params: dict) -> dict:
        return {
            "controller_id": self.catalog.controller_id,
            "secret": self.catalog.secret,
            "company_name": self.catalog.company_name,
            "connector_host": self.catalog.connector_host,
            "connector_port": self.catalog.connector_port,
        }

    def _set_company_name(self, params: dict) -> None:
        self.catalog.set_company_name(params["company_name"])

    def _set_connector(self, params: dict) -> None:
        self.catalog.set_connector(params["host"], params["port"])

    def _point_to(self, params: dict) -> None:
        self.transport.point_to(params["host"], params["port"])

    def _get_status(self, params: dict) -> dict:
        return {
            "connected": self.transport.connected,
            "server_reachable": self.transport.server_reachable,
            "last_error": self.transport.last_error,
        }

    def _list_devices(self, params: dict) -> list[dict]:
        return self.catalog.list_devices()

    def _get_device(self, params: dict) -> dict | None:
        return self.catalog.get_device(params["device_id"])

    def _add_device(self, params: dict) -> str:
        # Quem chama (ipc_client.RemoteCatalog) ainda precisa mandar
        # "notify_catalog_changed" à parte, igual gui/window.py faz com os
        # objetos reais (ControllerWindow._after_catalog_change) - mesmo
        # desenho dos dois lados, sem fundir responsabilidade de
        # catalog/transport aqui que não existe no caso local.
        return self.catalog.add_device(
            params["label"], params["type_"], params["brand"],
            params["connection"], params.get("settings"),
        )

    def _update_device(self, params: dict) -> None:
        self.catalog.update_device(
            params["device_id"], params["label"], params["type_"], params["brand"],
            params["connection"], params.get("settings"),
        )

    def _remove_device(self, params: dict) -> None:
        self.catalog.remove_device(params["device_id"])

    def _notify_catalog_changed(self, params: dict) -> None:
        self.transport.notify_catalog_changed()

    def _list_history(self, params: dict) -> list[dict]:
        return print_history.listar(limite=params.get("limite", 200))

    def _get_settings(self, params: dict) -> dict:
        return {
            "atualizacao_automatica": self.catalog.atualizacao_automatica,
            "guardar_historico": self.catalog.guardar_historico,
        }

    def _set_atualizacao_automatica(self, params: dict) -> None:
        self.catalog.set_atualizacao_automatica(params["ativa"])

    def _set_guardar_historico(self, params: dict) -> None:
        self.catalog.set_guardar_historico(params["ativo"])

    def _get_version(self, params: dict) -> str:
        return version.__version__

    def _esta_em_instalacao_real(self, params: dict) -> bool:
        return updater.esta_em_instalacao_real()

    def _consultar_ultima_release(self, params: dict) -> dict | None:
        return updater.consultar_ultima_release()

    def _versao_mais_nova(self, params: dict) -> bool:
        return updater.versao_mais_nova(params["tag"])

    def _forcar_atualizacao(self, params: dict) -> bool:
        # Se devolver True, o updater já reiniciou o serviço (systemd
        # Restart=on-failure sobe de novo) - a conexão IPC desse cliente
        # vai cair sozinha, igual o Windows derruba a janela pra reabrir.
        return updater.verificar_e_atualizar(forcar=True)


_COMANDOS = {
    "get_identity": IPCServer._get_identity,
    "set_company_name": IPCServer._set_company_name,
    "set_connector": IPCServer._set_connector,
    "point_to": IPCServer._point_to,
    "get_status": IPCServer._get_status,
    "list_devices": IPCServer._list_devices,
    "get_device": IPCServer._get_device,
    "add_device": IPCServer._add_device,
    "update_device": IPCServer._update_device,
    "remove_device": IPCServer._remove_device,
    "notify_catalog_changed": IPCServer._notify_catalog_changed,
    "list_history": IPCServer._list_history,
    "get_settings": IPCServer._get_settings,
    "set_atualizacao_automatica": IPCServer._set_atualizacao_automatica,
    "set_guardar_historico": IPCServer._set_guardar_historico,
    "get_version": IPCServer._get_version,
    "esta_em_instalacao_real": IPCServer._esta_em_instalacao_real,
    "consultar_ultima_release": IPCServer._consultar_ultima_release,
    "versao_mais_nova": IPCServer._versao_mais_nova,
    "forcar_atualizacao": IPCServer._forcar_atualizacao,
}
