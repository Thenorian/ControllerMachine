from core import *

class API(APICore):
    def __init__(self, host, API_PORT):
        super.__init__()
        self.host = host
        self.API_PORT = API_PORT
        self.app = FastAPI()

        # Rotas FastAPI
        @self.app.get("/", response_class=HTMLResponse)
        def home():
            with open("index.html", "r", encoding="utf-8") as f:
                return f.read()

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