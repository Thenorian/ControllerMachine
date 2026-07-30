"""
ControllerConnector — módulo embutido para o Simple ERP.

Este arquivo é pensado para ser copiado (ou instalado via requirements-server.txt,
que hoje não lista nada — usa só a biblioteca padrão do Python) direto dentro do
Simple ERP. Ele NÃO é um servidor separado: é uma classe que o Simple ERP
instancia e roda numa thread própria.

Responsabilidade única: manter os sockets TCP persistentes com os Controller
Machine (uma conexão por loja), saber quem está online e repassar jobs. Nada
de ESC/POS, layout de balança ou renderização de NFC-e acontece aqui — isso é
todo processado do outro lado, no Controller Machine. Este módulo só "sabe
enviar informação".

Uso típico dentro do Simple ERP:

    from server.connector import ControllerConnector

    def check_auth(controller_id: str, secret: str) -> bool:
        return meu_banco.controller_tem_acesso(controller_id, secret)

    def on_event(event: str, payload: dict):
        # opcional — ex.: atualizar um badge de "impressora online" na tela
        logging.info(f"[controller] {event}: {payload}")

    connector = ControllerConnector(auth_check=check_auth, on_event=on_event)
    connector.start()  # não bloqueia — roda numa thread daemon própria

    connector.is_online(controller_id)
    connector.send_print_job(controller_id, device_id, "raw", base64_bytes)
    connector.send_scale_update(controller_id, device_id, produtos)

    # ao encerrar o Simple ERP:
    connector.stop()
"""
from __future__ import annotations

import json
import logging
import queue
import socket
import threading
import time
import uuid

logger = logging.getLogger("controller_connector")


class ControllerConnector:
    def __init__(self, auth_check, host: str = "0.0.0.0", port: int = 7689, on_event=None):
        """
        auth_check: callable(controller_id: str, secret: str) -> bool
            Chamado a cada tentativa de registro. Quem sabe se aquele
            controller_id pertence a uma empresa com acesso ativo é o
            Simple ERP — este módulo não guarda essa informação.

        on_event: callable(event: str, payload: dict) -> None, opcional
            Eventos emitidos: "controller_connected", "controller_disconnected",
            "device_catalog_updated", "device_status".
        """
        self.auth_check = auth_check
        self.host = host
        self.port = port
        self.on_event = on_event

        self._server_socket: socket.socket | None = None
        self._clients: dict[str, dict] = {}  # controller_id -> {conn, addr, devices, last_seen}
        self._lock = threading.RLock()
        self._pending: dict[str, "queue.Queue"] = {}  # job_id -> fila esperando o ack
        self._running = False
        self._accept_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen()
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        logger.info(f"[ControllerConnector] ouvindo em {self.host}:{self.port}")

    def stop(self) -> None:
        self._running = False
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
        with self._lock:
            for entry in self._clients.values():
                try:
                    entry["conn"].close()
                except OSError:
                    pass
            self._clients.clear()

    # ------------------------------------------------------------------ #
    # Consultas (síncronas, seguras de chamar da thread principal do ERP)
    # ------------------------------------------------------------------ #

    def is_online(self, controller_id: str, device_id: str | None = None) -> bool:
        with self._lock:
            entry = self._clients.get(controller_id)
            if not entry:
                return False
            if device_id is None:
                return True
            return device_id in entry.get("devices", {})

    def list_devices(self, controller_id: str) -> dict:
        """Devolve o catálogo que o Controller Machine anunciou da última vez.
        Só reflete o que o Controller relatou — o Simple ERP quem decide como
        guardar label/localização a partir daqui."""
        with self._lock:
            entry = self._clients.get(controller_id)
            return dict(entry["devices"]) if entry else {}

    def list_online_controllers(self) -> list[str]:
        with self._lock:
            return list(self._clients.keys())

    # ------------------------------------------------------------------ #
    # Envio de job — chamadas bloqueantes (rodam na thread de quem chamou,
    # não na thread do connector; se for chamar do request-handler do ERP,
    # considere rodar num executor/threadpool próprio do lado do ERP)
    # ------------------------------------------------------------------ #

    def send_print_job(self, controller_id: str, device_id: str, data_type: str, data_base64: str, timeout: float = 10) -> dict:
        return self._send_job(controller_id, {
            "kind": "print",
            "device_id": device_id,
            "data_type": data_type,  # "raw" | "pdf" | "escpos"
            "data": data_base64,
        }, timeout)

    def send_fiscal_job(self, controller_id: str, device_id: str, nfce_payload: dict, timeout: float = 10) -> dict:
        return self._send_job(controller_id, {
            "kind": "print_fiscal_nfce",
            "device_id": device_id,
            "data": nfce_payload,
        }, timeout)

    def send_scale_update(self, controller_id: str, device_id: str, products: list[dict], timeout: float = 15) -> dict:
        return self._send_job(controller_id, {
            "kind": "scale_update",
            "device_id": device_id,
            "products": products,
        }, timeout)

    def _send_job(self, controller_id: str, job_body: dict, timeout: float) -> dict:
        with self._lock:
            entry = self._clients.get(controller_id)
        if not entry:
            return {"status": "error", "message": "controller offline"}

        job_id = str(uuid.uuid4())
        ack_queue: "queue.Queue" = queue.Queue(maxsize=1)
        self._pending[job_id] = ack_queue

        message = {"type": "job", "job_id": job_id, **job_body}
        try:
            entry["conn"].sendall((json.dumps(message) + "\n").encode("utf-8"))
        except OSError as err:
            self._pending.pop(job_id, None)
            return {"status": "error", "message": f"falha ao enviar: {err}"}

        try:
            return ack_queue.get(timeout=timeout)
        except queue.Empty:
            return {"status": "timeout", "job_id": job_id}
        finally:
            self._pending.pop(job_id, None)

    # ------------------------------------------------------------------ #
    # Laço de aceitação / leitura (thread própria)
    # ------------------------------------------------------------------ #

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True).start()

    def _handle_client(self, conn: socket.socket, addr) -> None:
        controller_id = None
        buffer = b""
        try:
            conn.settimeout(30)
            buffer, msg = self._read_message(conn, buffer)
            if not msg or msg.get("type") != "register":
                conn.close()
                return

            controller_id = msg.get("controller_id")
            secret = msg.get("secret", "")
            if not controller_id or not self.auth_check(controller_id, secret):
                self._send_raw(conn, {"type": "register_ack", "status": "error", "message": "não autorizado"})
                conn.close()
                return

            with self._lock:
                self._clients[controller_id] = {
                    "conn": conn,
                    "addr": addr,
                    "devices": msg.get("devices", {}),
                    "last_seen": time.time(),
                }
            self._send_raw(conn, {"type": "register_ack", "status": "ok"})
            self._emit("controller_connected", {"controller_id": controller_id, "addr": str(addr)})

            conn.settimeout(None)
            while self._running:
                buffer, msg = self._read_message(conn, buffer)
                if msg is None:
                    break
                self._on_message(controller_id, msg)

        except (OSError, json.JSONDecodeError) as err:
            logger.warning(f"[ControllerConnector] {controller_id or addr}: {err}")
        finally:
            with self._lock:
                self._clients.pop(controller_id, None)
            conn.close()
            if controller_id:
                self._emit("controller_disconnected", {"controller_id": controller_id})

    def _on_message(self, controller_id: str, msg: dict) -> None:
        msg_type = msg.get("type")

        if msg_type == "job_ack":
            job_id = msg.get("job_id")
            q = self._pending.get(job_id)
            if q is not None:
                q.put({"status": msg.get("status", "unknown"), "message": msg.get("message"), "job_id": job_id})

        elif msg_type == "device_catalog":
            devices = msg.get("devices", {})
            with self._lock:
                entry = self._clients.get(controller_id)
                if entry:
                    entry["devices"] = devices
            self._emit("device_catalog_updated", {"controller_id": controller_id, "devices": devices})

        elif msg_type == "device_status":
            self._emit("device_status", {
                "controller_id": controller_id,
                "device_id": msg.get("device_id"),
                "status": msg.get("status"),
            })

    @staticmethod
    def _send_raw(conn: socket.socket, obj: dict) -> None:
        conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    @staticmethod
    def _read_message(conn: socket.socket, buffer: bytes):
        """Lê até achar um '\\n' (framing newline-delimited) — evita o bug
        clássico de `json.loads(conn.recv(4096))` quebrar quando uma mensagem
        chega partida em mais de um pacote TCP."""
        while b"\n" not in buffer:
            chunk = conn.recv(4096)
            if not chunk:
                return buffer, None
            buffer += chunk
        line, _, buffer = buffer.partition(b"\n")
        if not line.strip():
            return buffer, {}
        return buffer, json.loads(line.decode("utf-8"))

    def _emit(self, event: str, payload: dict) -> None:
        if self.on_event:
            try:
                self.on_event(event, payload)
            except Exception:
                logger.exception(f"[ControllerConnector] erro no callback on_event({event})")
