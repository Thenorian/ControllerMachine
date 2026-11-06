"""
Lado cliente do IPC local (ver ipc.py) - usado só pelo app gráfico do
Linux (main.py::run_linux_gui), que roda num processo separado do serviço
e "controla remoto" ele por aqui. As três classes abaixo têm a mesma
interface (mesmos nomes de propriedade/método) que DeviceCatalog/
ControllerTransport/gui.window.LocalUpdaterFacade - gui/window.py usa uma
ou outra sem precisar saber a diferença.
"""
from __future__ import annotations

import socket
import threading

from ipc import recv_json, send_json, socket_path


class ServicoIndisponivel(RuntimeError):
    """O serviço (systemd) não está rodando, ou a conexão com ele caiu no
    meio de uma chamada - quem usa isso (gui/window.py, por enquanto só
    via try/except nos pontos que já tratavam erro de rede) deve avisar o
    operador e deixar ele tentar de novo, nunca travar a janela."""


class _IPCConnection:
    def __init__(self):
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._lock = threading.Lock()

    def call(self, comando: str, **params):
        with self._lock:
            if self._sock is None:
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(10)
                    sock.connect(str(socket_path()))
                except OSError as err:
                    raise ServicoIndisponivel(
                        "Não foi possível conectar ao serviço do Controller Machine "
                        "(ele está rodando? `systemctl status controller-machine`)"
                    ) from err
                self._sock = sock
                self._buffer = b""

            try:
                send_json(self._sock, {"comando": comando, "params": params})
                self._buffer, resposta = recv_json(self._sock, self._buffer)
            except OSError as err:
                self._sock = None
                raise ServicoIndisponivel("Conexão com o serviço caiu no meio da chamada") from err

            if resposta is None:
                self._sock = None
                raise ServicoIndisponivel("Serviço encerrou a conexão")
            if resposta.get("status") != "ok":
                raise RuntimeError(resposta.get("message") or "erro desconhecido no serviço")
            return resposta.get("resultado")


class RemoteCatalog:
    """Mesma interface pública de catalog.DeviceCatalog - cada propriedade/
    método vira uma chamada IPC (ver ipc_server.py). Sem cache: cada
    acesso busca o valor atual do serviço - socket Unix local é rápido
    o bastante pra isso não ser gargalo numa tela de configuração aberta
    ocasionalmente."""

    def __init__(self, conexao: _IPCConnection):
        self._conexao = conexao

    @property
    def controller_id(self) -> str:
        return self._conexao.call("get_identity")["controller_id"]

    @property
    def secret(self) -> str:
        return self._conexao.call("get_identity")["secret"]

    @property
    def company_name(self) -> str:
        return self._conexao.call("get_identity")["company_name"]

    @property
    def connector_host(self) -> str:
        return self._conexao.call("get_identity")["connector_host"]

    @property
    def connector_port(self) -> int:
        return self._conexao.call("get_identity")["connector_port"]

    @property
    def atualizacao_automatica(self) -> bool:
        return self._conexao.call("get_settings")["atualizacao_automatica"]

    @property
    def guardar_historico(self) -> bool:
        return self._conexao.call("get_settings")["guardar_historico"]

    def set_company_name(self, company_name: str) -> None:
        self._conexao.call("set_company_name", company_name=company_name)

    def set_connector(self, host: str, port: int) -> None:
        self._conexao.call("set_connector", host=host, port=port)

    def set_atualizacao_automatica(self, ativa: bool) -> None:
        self._conexao.call("set_atualizacao_automatica", ativa=ativa)

    def set_guardar_historico(self, ativo: bool) -> None:
        self._conexao.call("set_guardar_historico", ativo=ativo)

    def list_devices(self) -> list[dict]:
        return self._conexao.call("list_devices")

    def get_device(self, device_id: str) -> dict | None:
        return self._conexao.call("get_device", device_id=device_id)

    def add_device(self, label, type_, brand, connection, settings=None) -> str:
        return self._conexao.call(
            "add_device", label=label, type_=type_, brand=brand,
            connection=connection, settings=settings,
        )

    def update_device(self, device_id, label, type_, brand, connection, settings=None) -> None:
        self._conexao.call(
            "update_device", device_id=device_id, label=label, type_=type_, brand=brand,
            connection=connection, settings=settings,
        )

    def remove_device(self, device_id: str) -> None:
        self._conexao.call("remove_device", device_id=device_id)


class RemoteTransport:
    """Mesma interface pública de transport.ControllerTransport - só a
    parte que gui/window.py realmente usa (status de conexão, apontar pra
    outro servidor, avisar que o catálogo mudou)."""

    def __init__(self, conexao: _IPCConnection):
        self._conexao = conexao

    @property
    def connected(self) -> bool:
        return self._conexao.call("get_status")["connected"]

    @property
    def server_reachable(self) -> bool:
        return self._conexao.call("get_status")["server_reachable"]

    @property
    def last_error(self) -> str | None:
        return self._conexao.call("get_status")["last_error"]

    def point_to(self, host: str, port: int) -> None:
        self._conexao.call("point_to", host=host, port=port)

    def notify_catalog_changed(self) -> None:
        self._conexao.call("notify_catalog_changed")


class RemoteUpdaterFacade:
    """Mesma interface de gui.window.LocalUpdaterFacade - ver lá o porquê
    de existirem os dois."""

    def __init__(self, conexao: _IPCConnection):
        self._conexao = conexao

    def get_version(self) -> str:
        return self._conexao.call("get_version")

    def esta_em_instalacao_real(self) -> bool:
        return self._conexao.call("esta_em_instalacao_real")

    def consultar_ultima_release(self) -> dict | None:
        return self._conexao.call("consultar_ultima_release")

    def versao_mais_nova(self, tag: str) -> bool:
        return self._conexao.call("versao_mais_nova", tag=tag)

    def forcar_atualizacao(self) -> bool:
        return self._conexao.call("forcar_atualizacao")


def criar_proxies() -> tuple[RemoteCatalog, RemoteTransport, RemoteUpdaterFacade]:
    """Uma única conexão (criada sob demanda, reconecta sozinha a cada
    chamada se tiver caído - ver _IPCConnection) compartilhada pelos três
    proxies - não tem motivo pra manter sockets separados pra cada um."""
    conexao = _IPCConnection()
    return RemoteCatalog(conexao), RemoteTransport(conexao), RemoteUpdaterFacade(conexao)
