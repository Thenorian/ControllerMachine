# server/ — módulo embutido pra quem for integrar

Isto não é um servidor à parte, e não é exclusivo do Simple ERP — é código
que **qualquer sistema** (ERP, PDV, o que for) importa direto dentro do
próprio processo dele, pra saber quais lojas/dispositivos estão online e
mandar jobs de impressão/balança sem precisar chamar nenhuma API externa.
A Thenorian usa isso no Simple ERP — é a implementação de referência nos
exemplos abaixo — mas nada aqui depende dele.

## Como embutir no seu sistema

1. Copie a pasta `server/` inteira pra dentro do repositório do seu
   sistema (`connector.py` + `templates.py` + `server.py` — só biblioteca
   padrão do Python, sem dependência de mais nada deste repo).
2. Escreva uma função `check_auth(controller_id, secret) -> bool` que
   consulte o seu próprio banco (isso é responsabilidade de quem integra,
   não deste módulo — nem `ControllerConnector` nem `Server` guardam ou
   sabem nada sobre empresas, licenças ou qualquer regra de negócio de
   quem os usa).
3. Suba o `Server` numa thread própria, junto com o resto do sistema:

   ```python
   from server.server import Server

   server = Server(auth_check=check_auth)
   server.start()  # não bloqueia — thread daemon própria
   ```

4. Use os métodos de consulta/envio (`is_online`, `send_print_job`,
   `send_fiscal_job`, `send_scale_update`, `push_template`) de onde precisar
   no sistema — uma tela de PDV, um botão "reimprimir", etc. `Server` é uma
   fachada em volta de `ControllerConnector` — quem só precisa da ponte
   (sem o modelo de template orientado a objetos) pode continuar usando
   `ControllerConnector` direto, sem essa camada extra.

## Layout de nota fiscal/cupom é decisão de quem integra, não do Controller Machine

O Controller Machine **nunca** decide layout por conta própria — ele só
aplica o `template` que chegar por push (ver contrato completo do dict em
`client/devices/printer_fiscal.py`). Quando uma regra fiscal ou o leiaute
mudar, é isso que o sistema que embutiu o `Server` manda pra cada controller
da empresa — nunca edição feita loja por loja no Controller Machine (não
existe editor de layout do lado do client, de propósito).

Do lado de quem integrou, `templates.py` modela isso de forma orientada a
objetos: `Server.template` é um `NFCe`/`NFe`/`Cupom` por tipo de documento
(cada um com seções reutilizáveis estilo Tkinter — `Text(text=..., bold=...)`,
`QRCode(size=..., error_correction=...)` — além de `mostrar_ie`, `pdv_label`
e `fonte_pequena`), e `.to_dict()` serializa pro mesmo dict de sempre. Duas
formas de mudar o layout:

```python
# 1. ajustar atributo direto
server.template.NFCe.header.text = "Loja Centro — Rua das Flores, 123"
server.template.NFCe.qr_code.size = 8
server.template.NFCe.pdv_label = "Caixa 1"

# 2. herdar e sobrescrever comportamento (quando não é só um valor)
from server.templates import NFCe

class MinhaNFCe(NFCe):
    def to_dict(self):
        d = super().to_dict()
        d["mensagem_empresa"] = d["mensagem_empresa"].upper()
        return d

server.template.NFCe = MinhaNFCe()
```

E pra empresa inteira, sempre que a regra mudar:

```python
for controller_id in controllers_da_empresa(empresa_id):
    for device_id, info in server.list_devices(controller_id).items():
        if info["type"] == "printer_fiscal":
            server.push_template(controller_id, device_id, "NFCe")
```

## O que este módulo faz e o que ele não faz

- Faz: mantém o socket TCP com cada Controller Machine, sabe quem está
  conectado agora, repassa job e espera o `ack`.
- Não faz: não monta ESC/POS, não sabe layout de balança, não sabe nada de
  NFC-e, não guarda cadastro de empresa/dispositivo em banco nenhum. Tudo
  isso é do lado do Controller Machine (`client/`) ou de quem integrou.

Documentação completa da arquitetura pra quem for usar/contribuir está na
[Wiki deste repositório](../../wiki). O vault do Obsidian citado em outros
lugares é documentação **interna da Thenorian** (como o Simple ERP integra
de fato, licenciamento, etc.) — não é necessário pra embutir isto no seu
próprio sistema.

## Testar sem nenhum sistema de verdade integrado

`python example_usage.py` sobe um connector de teste com auth via SQLite
solto — serve só pra testar a conexão de ponta a ponta com um Controller
Machine local, não representa como nenhum sistema real vai usar (Simple
ERP ou qualquer outro).
