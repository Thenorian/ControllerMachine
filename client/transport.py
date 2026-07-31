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
import socket
import threading
import time
from typing import Callable

logger = logging.getLogger("transport")


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
            try:
                self._conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._conn.connect((self.host, self.port))

                self._send({
                    "type": "register",
                    "controller_id": self.controller_id,
                    "secret": self.secret,
                    "devices": self.announce_payload(),
                })

                buffer, msg = self._read_message(b"")
                if not msg or msg.get("status") != "ok":
                    raise ConnectionError(f"registro recusado: {msg}")

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
