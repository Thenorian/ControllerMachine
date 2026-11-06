"""
IPC local entre o serviço do Controller Machine (que fica em segundo plano,
dono de verdade do catálogo/conexão com o connector) e o app gráfico
(Tkinter, só um visualizador/controle remoto - ver gui_linux.py e
main.py::run_linux_gui). Existe só no Linux: no Windows, serviço e janela
sempre foram o mesmo processo (ver run_windows em main.py), sem motivo pra
separar.

Socket Unix, não TCP - é sempre a mesma máquina (o app gráfico só faz
sentido rodando fisicamente no PDV, de frente pra impressora), então não
precisa expor nada em rede, e permissão de arquivo já resolve controle de
acesso de graça. Framing idêntico ao já usado em transport.py/connector.py
(JSON por linha) - mesmo estilo do resto do projeto, sem reinventar.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def socket_path() -> Path:
    """`RUNTIME_DIRECTORY` é posto pelo systemd quando a unit usa
    `RuntimeDirectory=` (ver service_linux.py::UNIT_TEMPLATE) - é limpo e
    recriado sozinho a cada start, com a posse certa, sem o código precisar
    se preocupar em criar pasta em /run (que normalmente exige root). Fora
    do systemd (desenvolvimento, `python main.py` direto), cai num arquivo
    em /tmp mesmo - mais frágil (não limpa sozinho), mas serve pra testar."""
    runtime_dir = os.environ.get("RUNTIME_DIRECTORY")
    if runtime_dir:
        return Path(runtime_dir) / "ipc.sock"
    return Path(tempfile.gettempdir()) / "controller-machine-ipc.sock"


# Qualquer usuário local da máquina pode controlar o serviço pela GUI -
# mesma confiança que já existia (quem tem sessão no PDV já podia editar o
# config.json na mão ou reiniciar o serviço via systemctl). 0o666 porque o
# socket nasce com umask do processo (que roda como root/serviço) - sem
# isso um usuário comum não consegue nem abrir o socket.
SOCKET_PERMISSIONS = 0o666


def send_json(sock, obj: dict) -> None:
    sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))


def recv_json(sock, buffer: bytes) -> tuple[bytes, dict | None]:
    """Devolve (buffer_restante, mensagem) - mensagem None quando a conexão
    fechou (igual ao mesmo contrato de transport.py::_read_message)."""
    while b"\n" not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            return buffer, None
        buffer += chunk
    line, _, buffer = buffer.partition(b"\n")
    if not line.strip():
        return buffer, {}
    return buffer, json.loads(line.decode("utf-8"))
