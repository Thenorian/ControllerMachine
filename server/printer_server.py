from api import *

class PrinterServer(API):
    def __init__(self, host:str="0.0.0.0", TCP_PORT:int=7689, API_PORT=7688):
        super.__init__(
            host=host, 
            API_PORT=API_PORT
        )
        self.clients = {}  # {client_id: {'conn': conn, 'addr': addr}}
        self.lock = threading.Lock()

        # Configurações
        self.HOST = host
        self.TCP_PORT = TCP_PORT  # Porta para sockets TCP

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