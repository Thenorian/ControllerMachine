# Sistema de Impressão Remota

Sistema simples e robusto para enviar impressões de um servidor externo para impressoras locais em máquinas clientes (Windows ou Linux).

## Funcionalidades

- Envio de PDF, texto ou dados raw (ESC/POS, ZPL, etc.)
- Fila de impressão com reconexão automática
- Status da impressora
- Autenticação por UUID
- Agrupamento por empresa/grupo
- Interface web simples + API REST
- Cliente roda em segundo plano (ícone na bandeja)

## Instalação

### 1. Servidor

```bash
cd server
pip install -r requirements-server.txt
python main.py
```

O servidor vai gerar e exibir duas API Keys de exemplo.
Acesse a interface web em http://SEU_IP:7689

### 2. Cliente (Windows ou Linux)
```Bash
cd client
pip install -r requirements-client.txt
```
#### Linux - dependências do sistema:

```Bash
sudo apt install libcups2-dev python3-gi gir1.2-gtk-3.0
````
Edite o final do arquivo cliente.py com:

CLIENT_ID: nome único da máquina/loja
AUTH_KEY: um dos UUIDs gerados pelo servidor
GROUP: mesmo grupo da API key que vai enviar jobs

Execute:
```Bash
python cliente.py
```
O programa ficará em segundo plano (ícone verde na bandeja do Windows ou Linux).
### Enviar uma impressão (exemplo com curl)

```Bash
curl -X POST http://SEU_IP:8080/api/send_job \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "uuid-gerado-pelo-servidor",
    "group": "empresa1",
    "type": "pdf",
    "data": "'$(base64 -w 0 seu_arquivo.pdf)'"
  }'
```