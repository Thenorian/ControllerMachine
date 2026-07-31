# client/ — Controller Machine

Roda na loja do cliente. Documentação completa (protocolo, arquitetura) está
no vault do Obsidian — handoff "Controller Machine" — este arquivo é só
referência rápida do que está neste diretório.

## Rodar

```bash
pip install -r requirements-client.txt
python main.py
```

Linux: `python main.py --install-service` registra como serviço systemd
(precisa de `sudo`). `python main.py --uninstall-service` remove.
Windows: `python main.py --install-autostart` cria atalho na pasta Startup.

## Apontar para outro servidor

Na janela (Windows), campo "Servidor" + "Porta" no topo, botão "Salvar e
reconectar" — grava em `config.json` (`catalog.set_connector`) e força
reconexão imediata sem esperar o backoff de retry (`transport.point_to`).
No Linux (sem GUI), editar `connector_host`/`connector_port` direto no
`config.json` e reiniciar o serviço (`systemctl restart controller-machine`).

## `config.json`

Windows: `%APPDATA%\ControllerMachine\config.json`.
Linux: `/etc/controller-machine/config.json` (fallback:
`~/.config/controller-machine/config.json` sem permissão em `/etc`).

Gerado automaticamente na primeira execução (`config.py::default_config`).
**Nunca editar `controller_id`, `secret` ou qualquer `device_id` à mão** —
são a garantia de identidade única e permanente que o Simple ERP depende
para nunca perder a referência a um dispositivo, mesmo que ele seja
renomeado ou realocado do lado do Simple ERP.

```json
{
  "connector_host": "meuservidor.exemplo.com",
  "connector_port": 7689,
  "controller_id": "uuid — gerado automaticamente, não editar",
  "secret": "uuid — gerado automaticamente, não editar",
  "company_name": "Nome da loja (só exibição local)",
  "devices": [
    {
      "device_id": "uuid — gerado automaticamente, não editar",
      "label": "Impressora do Caixa 1",
      "type": "printer_common",
      "brand": "generic",
      "connection": {"kind": "os_printer", "os_name": "Xerox Phaser 3020 (USB)"}
    }
  ]
}
```

## Estrutura

- `config.py` / `catalog.py` — persistência e regra de IDs imutáveis.
- `discovery.py` — impressoras instaladas no SO (Windows/Linux).
- `transport.py` — socket com o connector, reconexão automática.
- `devices/` — execução dos jobs (impressão comum, fiscal/NFC-e, balança
  por marca em `devices/scale/`).
- `gui/` — janela Tkinter + tray do Windows.
- `service_linux.py` — instalador do serviço systemd.
- `assets/generate_icon.py` — gera o ícone pixel-art usado na bandeja.
