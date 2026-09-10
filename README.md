# Controller Machine

Programa que roda na loja do cliente e dá acesso a impressoras (comuns e
fiscais/NFC-e) e balanças da rede local pra um sistema (ERP, PDV, o que
for) rodando fora dessa rede — sem precisar estar na mesma rede do
cliente, e contornando CGNAT.

Projeto **open source (GPLv3)**. A Thenorian usa isso embutido no Simple
ERP — é a implementação de referência, citada nos exemplos — mas nada
aqui depende dele: `server/` não guarda nem conhece nada de empresa,
licença ou banco de dados de ninguém (`auth_check` é sempre um callback
que quem for embutir implementa), então qualquer sistema pode embutir a
mesma ponte pro próprio caso. Ver a [Wiki](../../wiki) pra documentação
completa da arquitetura.

Documentação interna adicional (específica da Thenorian: como o Simple
ERP integra de fato, licenciamento, etc.) está no vault do Obsidian da
Thenorian, handoff "Controller Machine" — não é necessária pra usar ou
contribuir com este repositório.

## Componentes

- **`server/`** — não é um servidor separado. É código que **quem for
  integrar copia pro próprio processo** (`ControllerConnector` — só
  transporte — e a fachada `Server`, que adiciona o modelo de template
  orientado a objetos) e roda numa thread própria — ver `server/README.md`.
- **`client/`** — o Controller Machine em si, roda na loja. Windows: ícone
  na bandeja + janela de cadastro. Linux: serviço systemd (`python main.py
  --install-service`).

## Testar localmente (sem o Simple ERP de verdade)

Terminal 1 — sobe um connector de teste:

```bash
cd server
python example_usage.py
```

Terminal 2 — client, configurado pra apontar pro connector de teste
(controller_id/secret de exemplo já cadastrados pelo `example_usage.py`):

```bash
cd client
pip install -r requirements-client.txt
python main.py
```

No Windows, isso abre o ícone na bandeja + a janela de cadastro (some pra
bandeja sozinha se já tiver dispositivo cadastrado). No Linux, roda em
primeiro plano até você instalar como serviço.

### Linux — dependências do sistema

```bash
sudo apt install libcups2-dev python3-gi gir1.2-gtk-3.0
```

## Balança — arquivos de exemplo

`Exemplos Balança/` tem arquivos reais gerados por diferentes marcas de
balança (Ramuza/Atena, Toledo Prix, Filizola, Toledo MGV5) — é a partir
deles que os formatters em `client/devices/scale/` foram construídos. O
formatter do Toledo MGV5 foi conferido byte a byte contra esses exemplos; os
demais ainda são esqueleto (ver documentação no Obsidian pra detalhes de
quais marcas estão prontas).
