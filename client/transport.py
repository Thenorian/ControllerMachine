"""
Conexão persistente com o connector embutido no Simple ERP. O Controller
Machine sempre inicia a conexão de saída (é assim que se contorna CGNAT —
ver documentação) e fica pendurado nela, reconectando sozinho se cair.

Framing: JSON delimitado por '\\n', igual ao lado do connector
(server/connector.py) — precisa ser simétrico dos dois lados.
"""
from __future__ import annotations

import json
import logging
import platform
import socket
import threading
import time
from typing import Callable

logger = logging.getLogger("transport")

# Sem isso, um socket.recv() bloqueado fica esperando pra sempre se o lado
# de lá some sem mandar um FIN/RST (ex.: `docker rm -f` no deploy do Simple
# ERP mata o processo, mas nem sempre o RST chega no cliente por causa da
# rede/NAT no meio do caminho) - o cliente ficava com uma conexão zumbi,
# achando que ainda tava tudo bem, e só reconectava se alguém clicasse
# "Salvar e reconectar" na tela (que força fechar o socket na unha). Com
# keepalive, o próprio SO detecta a conexão morta e devolve erro no recv(),
# que já cai no loop de reconexão que já existia (_connect_loop).
_KEEPALIVE_IDLE_SECONDS = 10   # começa a sondar depois de 10s sem tráfego
_KEEPALIVE_INTERVAL_SECONDS = 5  # intervalo entre sondas
_KEEPALIVE_PROBES = 3          # desiste (recv() erra) depois de 3 sondas sem resposta


def _enable_keepalive(conn: socket.socket) -> None:
    """Liga TCP keepalive multiplataforma - a sintonia fina (idle/interval/
    count) é Linux/macOS; no Windows entra via ioctl com outra API. Tudo
    dentro de try/except porque keepalive é uma otimização de detecção, não
    algo que deveria derrubar a conexão se a plataforma não suportar algum
    dos parâmetros."""
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        logger.warning("Não foi possível ligar SO_KEEPALIVE nesse socket")
        return

    system = platform.system()
    try:
        if system == "Windows":
            # SIO_KEEPALIVE_VALS: (on/off, idle_ms, interval_ms) - Windows não
            # tem um equivalente direto a TCP_KEEPCNT, só idle e interval.
            conn.ioctl(socket.SIO_KEEPALIVE_VALS, (
                1, _KEEPALIVE_IDLE_SECONDS * 1000, _KEEPALIVE_INTERVAL_SECONDS * 1000
            ))
        elif system in ("Linux", "Darwin") and hasattr(socket, "TCP_KEEPIDLE"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, _KEEPALIVE_IDLE_SECONDS)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, _KEEPALIVE_INTERVAL_SECONDS)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _KEEPALIVE_PROBES)
        elif system == "Darwin" and hasattr(socket, "TCP_KEEPALIVE"):
            # macOS mais antigo só tem o parâmetro combinado TCP_KEEPALIVE.
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, _KEEPALIVE_IDLE_SECONDS)
    except OSError:
        logger.warning(f"SO_KEEPALIVE ligado, mas não deu pra ajustar os tempos em {system}")


class ControllerTransport:
    def __init__(self, host: str, port: int, controller_id: str, secret: str,
                 announce_payload: Callable[[], dict], on_job: Callable[[dict], dict]):
        """
        announce_payload: callable() -> dict — chamado a cada (re)conexão pra
            pegar o catálogo de dispositivos atual (via DeviceCatalog.to_announce_payload).
        on_job: callable(job: dict) -> dict — processa o job recebido e
            devolve {"status": "done"|"error", "message": "..."} pra virar o ack.
        """
        self.host = host
        self.port = port
        self.controller_id = controller_id
        self.secret = secret
        self.announce_payload = announce_payload
        self.on_job = on_job

        self.running = False
        self.connected = False
        self.server_reachable = False  # TCP conectou (mesmo que o registro seja recusado depois)
        self.last_error: str | None = None  # motivo da última recusa de registro, se houver
        self._conn: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._retry_delay = 5
        self._max_retry_delay = 60
        self._wake_event = threading.Event()

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._connect_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.running = False
        self.connected = False
        if self._conn:
            try:
                self._conn.close()
            except OSError:
                pass

    def point_to(self, host: str, port: int) -> None:
        """Aponta pra outro servidor e força reconexão imediata (não espera
        o backoff de retry) — usado quando o usuário troca host/porta na
        janela e clica em salvar."""
        self.host = host
        self.port = port
        self._force_reconnect()

    def _force_reconnect(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except OSError:
                pass
        self._wake_event.set()

    def notify_catalog_changed(self) -> None:
        """Chamar depois de adicionar/remover/renomear um dispositivo
        localmente — reenvia o catálogo pro connector sem precisar reconectar."""
        if self.connected and self._conn:
            self._send({"type": "device_catalog", "devices": self.announce_payload()})

    def send_device_status(self, device_id: str, status: dict) -> None:
        if self.connected and self._conn:
            self._send({"type": "device_status", "device_id": device_id, "status": status})

    # ------------------------------------------------------------------ #

    def _connect_loop(self) -> None:
        delay = self._retry_delay
        while self.running:
            self.server_reachable = False
            try:
                self._conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._conn.connect((self.host, self.port))
                _enable_keepalive(self._conn)
                self.server_reachable = True  # TCP ok — mesmo que o registro falhe a seguir

                self._send({
                    "type": "register",
                    "controller_id": self.controller_id,
                    "secret": self.secret,
                    "devices": self.announce_payload(),
                })

                buffer, msg = self._read_message(b"")
                if not msg or msg.get("status") != "ok":
                    self.last_error = (msg or {}).get("message") or "registro recusado"
                    raise ConnectionError(f"registro recusado: {msg}")

                self.last_error = None
                logger.info("Conectado e registrado no connector")
                self.connected = True
                delay = self._retry_delay  # reseta o backoff após sucesso

                while self.running:
                    buffer, msg = self._read_message(buffer)
                    if msg is None:
                        raise ConnectionError("conexão encerrada pelo servidor")
                    if msg:
                        self._dispatch(msg)

            except (OSError, ConnectionError, json.JSONDecodeError) as err:
                logger.warning(f"Falha na conexão: {err}")
            finally:
                self.connected = False
                if self._conn:
                    try:
                        self._conn.close()
                    except OSError:
                        pass
                    self._conn = None

            if not self.running:
                break
            logger.info(f"Reconectando em {delay}s...")
            woke_early = self._wake_event.wait(delay)
            if woke_early:
                self._wake_event.clear()
                delay = self._retry_delay  # troca de servidor não deve herdar backoff acumulado
            else:
                delay = min(delay * 2, self._max_retry_delay)

    def _dispatch(self, msg: dict) -> None:
        if msg.get("type") != "job":
            return
        job_id = msg.get("job_id")
        try:
            result = self.on_job(msg)
        except Exception as err:
            logger.exception("Erro processando job")
            result = {"status": "error", "message": str(err)}

        self._send({
            "type": "job_ack",
            "job_id": job_id,
            "status": result.get("status", "error"),
            "message": result.get("message"),
        })

    def _send(self, obj: dict) -> None:
        if not self._conn:
            return
        self._conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    def _read_message(self, buffer: bytes):
        while b"\n" not in buffer:
            chunk = self._conn.recv(4096)
            if not chunk:
                return buffer, None
            buffer += chunk
        line, _, buffer = buffer.partition(b"\n")
        if not line.strip():
            return buffer, {}
        return buffer, json.loads(line.decode("utf-8"))
