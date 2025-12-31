# server/main.py
import socket
import threading
import json
import uuid
import sqlite3
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configurações
HOST = '0.0.0.0'
TCP_PORT = 7689  # Porta para sockets TCP
API_PORT = 7688  # Porta para FastAPI

# Inicializa SQLite com relacionamentos
conn_db = sqlite3.connect('printer_server.db', check_same_thread=False)
cursor = conn_db.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS empresas (
    empresa_id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_name TEXT UNIQUE NOT NULL,
    auth_key TEXT UNIQUE NOT NULL
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS printers (
    client_id TEXT PRIMARY KEY,
    empresa_id INTEGER NOT NULL,
    last_ip TEXT,
    last_connected TEXT,
    status JSON,
    FOREIGN KEY (empresa_id) REFERENCES empresas(empresa_id)
)
''')
conn_db.commit()

class PrinterServer:
    def __init__(self):
        self.clients = {}  # {client_id: {'conn': conn, 'addr': addr}}
        self.lock = threading.Lock()
        self.app = FastAPI()

        # Rotas FastAPI
        @self.app.get("/", response_class=HTMLResponse)
        async def index():
            with self.lock:
                empresas_html = ""
                for empresa, clients in self.load_empresas().items():
                    empresas_html += f"<li><b>{empresa}</b>: {', '.join(clients)}</li>"
            return f"""
            <h1>Printer Remote Server</h1>
            <p><strong>Empresas e Clientes:</strong></p>
            <ul>{empresas_html}</ul>
            <hr>
            <h2>API - Enviar Impressão</h2>
            <p>POST /api/send_job</p>
            <pre>{{
  "auth_key": "uuid-key-da-empresa",
  "empresa_name": "empresa1",     // opcional se auth_key já identifica
  "client_id": "uuid-client",     // opcional para enviar a um específico
  "type": "pdf|text|raw",
  "data": "base64_data"
}}</pre>
            <hr>
            <h2>API - Cadastrar Empresa</h2>
            <p>POST /api/create_empresa</p>
            <pre>{{"empresa_name": "empresa_nova"}}</pre>
            Retorna: {{"auth_key": "uuid-gerado"}}
            <h2>API - Cadastrar Máquina</h2>
            <p>POST /api/create_machine</p>
            <pre>{{"empresa_name": "empresa1"}}</pre>
            Retorna: {{"client_id": "uuid-gerado"}}
            """

        class JobRequest(BaseModel):
            auth_key: str
            empresa_name: str | None = None
            client_id: str | None = None
            type: str = "raw"
            data: str

        @self.app.post("/api/send_job")
        async def send_job(job: JobRequest):
            auth_key = job.auth_key
            if not self.validate_auth_key(auth_key):
                raise HTTPException(401, "Auth Key inválida")

            empresa_name = job.empresa_name or self.get_empresa_from_key(auth_key)
            client_id = job.client_id
            job_type = job.type
            job_data = job.data

            if not job_data:
                raise HTTPException(400, "Dados ausentes")

            sent = 0
            with self.lock:
                targets = [client_id] if client_id else self.load_clients_by_empresa(empresa_name)
                for cid in targets:
                    if cid in self.clients and self.send_print_job(cid, job_type, job_data):
                        sent += 1

            return {"status": "enviado", "alcancados": sent}

        class EmpresaRequest(BaseModel):
            empresa_name: str

        @self.app.post("/api/create_empresa")
        async def create_empresa(req: EmpresaRequest):
            empresa_name = req.empresa_name
            auth_key = str(uuid.uuid4())
            try:
                cursor.execute("INSERT INTO empresas (empresa_name, auth_key) VALUES (?, ?)", (empresa_name, auth_key))
                conn_db.commit()
                return {"status": "empresa criada", "auth_key": auth_key}
            except sqlite3.IntegrityError:
                raise HTTPException(400, "Empresa já existe")

        @self.app.post("/api/create_machine")
        async def create_machine(req: EmpresaRequest):
            empresa_name = req.empresa_name
            client_id = str(uuid.uuid4())

            cursor.execute("SELECT empresa_id FROM empresas WHERE empresa_name = ?", (empresa_name,))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(404, "Empresa não encontrada")
            empresa_id = row[0]

            try:
                cursor.execute('''
                INSERT INTO printers (client_id, empresa_id, last_ip, last_connected, status)
                VALUES (?, ?, ?, datetime('now'), '{}')
                ''', (client_id, empresa_id, 'pending'))
                conn_db.commit()
                return {"status": "máquina cadastrada", "client_id": client_id}
            except sqlite3.IntegrityError:
                raise HTTPException(400, "Erro ao cadastrar máquina")

        # Inicia socket TCP
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, TCP_PORT))
        self.server_socket.listen()

    def load_empresas(self):
        cursor.execute('''
        SELECT e.empresa_name, p.client_id
        FROM empresas e LEFT JOIN printers p ON e.empresa_id = p.empresa_id
        ''')
        empresas = {}
        for row in cursor.fetchall():
            empresa, cid = row
            if cid:
                empresas.setdefault(empresa, []).append(cid)
        return empresas

    def load_clients_by_empresa(self, empresa_name):
        cursor.execute('''
        SELECT p.client_id
        FROM printers p JOIN empresas e ON p.empresa_id = e.empresa_id
        WHERE e.empresa_name = ?
        ''', (empresa_name,))
        return [row[0] for row in cursor.fetchall()]

    def validate_auth_key(self, key):
        cursor.execute("SELECT 1 FROM empresas WHERE auth_key = ?", (key,))
        return cursor.fetchone() is not None

    def get_empresa_from_key(self, key):
        cursor.execute("SELECT empresa_name FROM empresas WHERE auth_key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def validate_client_id(self, client_id):
        cursor.execute("SELECT 1 FROM printers WHERE client_id = ?", (client_id,))
        return cursor.fetchone() is not None

    def start(self):
        logging.info(f"Servidor TCP em {HOST}:{TCP_PORT}")
        logging.info(f"API FastAPI em http://{HOST}:{API_PORT}")

        import uvicorn
        threading.Thread(target=uvicorn.run, args=(self.app,), kwargs={'host': HOST, 'port': API_PORT}, daemon=True).start()

        while True:
            conn, addr = self.server_socket.accept()
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

    def handle_client(self, conn, addr):
        client_id = None
        try:
            data = conn.recv(4096)
            if not data:
                return
            msg = json.loads(data.decode('utf-8'))

            if msg.get('type') != 'register':
                conn.close()
                return

            client_id = msg['client_id']

            # Valida UUID e se existe no DB
            try:
                uuid.UUID(client_id)
            except ValueError:
                conn.send(json.dumps({"status": "error", "message": "Client ID inválido"}).encode('utf-8'))
                conn.close()
                return

            if not self.validate_client_id(client_id):
                conn.send(json.dumps({"status": "error", "message": "Client ID não cadastrado"}).encode('utf-8'))
                conn.close()
                return

            # Atualiza no DB
            cursor.execute('''
            UPDATE printers SET last_ip = ?, last_connected = datetime('now') WHERE client_id = ?
            ''', (str(addr), client_id))
            conn_db.commit()

            with self.lock:
                self.clients[client_id] = {'conn': conn, 'addr': addr}

            conn.send(json.dumps({"status": "registered"}).encode('utf-8'))
            logging.info(f"Cliente registrado: {client_id} de {addr}")

            while True:
                data = conn.recv(4096)
                if not data:
                    break
                msg = json.loads(data.decode('utf-8'))
                if msg.get('type') == 'status_update':
                    cursor.execute("UPDATE printers SET status = ? WHERE client_id = ?", (json.dumps(msg['status']), client_id))
                    conn_db.commit()

        except Exception as e:
            logging.error(f"Erro com {client_id or addr}: {e}")
        finally:
            with self.lock:
                if client_id in self.clients:
                    del self.clients[client_id]
            conn.close()
            if client_id:
                cursor.execute("UPDATE printers SET last_connected = datetime('now') WHERE client_id = ?", (client_id,))
                conn_db.commit()
            logging.info(f"Cliente {client_id} desconectado")

    def send_print_job(self, client_id, job_type, job_data):
        with self.lock:
            if client_id not in self.clients:
                return False
            conn = self.clients[client_id]['conn']
        try:
            msg = {'type': 'print', 'job_type': job_type, 'data': job_data}
            conn.send(json.dumps(msg).encode('utf-8'))
            return True
        except:
            return False

if __name__ == '__main__':
    server = PrinterServer()
    server.start()