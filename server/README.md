# server/ — módulo embutido para o Simple ERP

Isto não é um servidor à parte. É o código que o **Simple ERP** importa
direto dentro do próprio processo dele, pra saber quais lojas/dispositivos
estão online e mandar jobs de impressão/balança sem precisar chamar nenhuma
API externa.

## Como embutir no Simple ERP

1. Copie `connector.py` pra dentro do repositório do Simple ERP (não tem
   dependência de mais nada deste repo — só biblioteca padrão do Python).
2. Escreva uma função `check_auth(controller_id, secret) -> bool` que
   consulte o banco do próprio Simple ERP (isso é responsabilidade do Simple
   ERP, não deste módulo — o connector não guarda nem sabe nada sobre
   empresas).
3. Suba o connector numa thread própria, junto com o resto do sistema:

   ```python
   from server.connector import ControllerConnector

   connector = ControllerConnector(auth_check=check_auth)
   connector.start()  # não bloqueia — thread daemon própria
   ```

4. Use os métodos de consulta/envio (`is_online`, `send_print_job`,
   `send_fiscal_job`, `send_scale_update`) de onde precisar no sistema —
   uma tela de PDV, um botão "reimprimir", etc.

## O que este módulo faz e o que ele não faz

- Faz: mantém o socket TCP com cada Controller Machine, sabe quem está
  conectado agora, repassa job e espera o `ack`.
- Não faz: não monta ESC/POS, não sabe layout de balança, não sabe nada de
  NFC-e, não guarda cadastro de empresa/dispositivo em banco nenhum. Tudo
  isso é do lado do Controller Machine (`client/`) ou do próprio Simple ERP.

Ver a documentação completa (protocolo, formato de `config.json` do client,
regra de IDs) no vault do Obsidian — handoff "Controller Machine" na pasta
`Documentação/interna/Simple  ERP/`.

## Testar sem o Simple ERP

`python example_usage.py` sobe um connector de teste com auth via SQLite
solto — serve só pra testar a conexão de ponta a ponta com um Controller
Machine local, não é como o Simple ERP vai usar de verdade.
