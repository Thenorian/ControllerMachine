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
- `gui/` — janela Tkinter + tray do Windows. `gui/template_editor.py`
  contém o editor de modelo de impressão (ver seção abaixo).
- `service_linux.py` — instalador do serviço systemd.
- `assets/generate_icon.py` — gera o ícone pixel-art usado na bandeja.
- `logging_setup.py` — logs em disco (`logs/` ao lado do programa, rotação
  diária, no máximo 25 arquivos).
- `installer/` — instaladores Windows/Linux (ver seção abaixo).

## Logs

Ficam em `logs/` ao lado de onde o programa está rodando (dentro da pasta
de instalação, ver `installer/` abaixo). Um arquivo por dia
(`controller-machine.log`, rotacionado à meia-noite), no máximo 25 arquivos
guardados — os mais antigos somem sozinhos (`logging_setup.py`).

## Modelo de impressão (DANFE NFC-e / Cupom)

Quem desenha o cupom/nota é sempre o Controller Machine
(`devices/printer_fiscal.py::render_danfe_nfce`) — o Simple ERP só manda
dados da venda (itens, totais, atendente, PDV...), nunca layout. Editar o
dispositivo do tipo "Impressora fiscal (DANFE)" na GUI (Windows) abre a
seção "Modelo de impressão":

- **Modo Básico**: mostrar/ocultar IE, título do cupom, mensagem padrão da
  empresa, tamanho/correção de erro do QR Code — qualquer usuário Admin,
  sempre dentro da estrutura fixa da NFC-e.
- **Modo Avançado** (botão "Modo Avançado (cupom)...", com aviso de
  confirmação — reservado à equipe Thenorian, toda alteração é logada em
  `logs/`): editor de blocos livre, reordena/adiciona/remove — mas **só
  vale pro cupom**. A trava é estrutural, não é validação: o renderer só lê
  `blocos_customizados` quando `tipo_documento="cupom"`, e o vocabulário de
  blocos (`devices/printer_fiscal.py::TIPOS_BLOCO_VALIDOS`) não tem QR
  Code/chave de acesso/protocolo como opção — não tem como um template mal
  configurado (nem editado à mão no `config.json`) tirar campo obrigatório
  de uma nota fiscal real.
- **Exportar/Importar modelo**: baixa/sobe o `template` inteiro como
  `.json` — configura uma impressora certa e replica pras outras sem
  reconfigurar campo por campo.

Tudo fica em `device["settings"]["template"]` no `config.json` local — sem
Linux (sem GUI ainda), editar essa chave direto no arquivo, mesmo padrão
do resto das configurações.

## Instaladores (Windows / Linux)

Nenhum instalador é buildado à mão nem versionado no repositório. A action
`.github/workflows/build-packages.yml` roda automaticamente toda vez que uma
release é publicada no GitHub, gera os três pacotes abaixo e anexa todos na
release (também dá pra disparar manualmente via `workflow_dispatch`, nesse
caso os pacotes saem como artifacts em vez de anexados a uma release):

- **`ControllerMachine.exe`** — o programa em si (via `ControllerMachine.spec`).
- **`ControllerMachineSetup.exe`** — instalador Windows (Tkinter,
  `installer/windows_installer.py`/`.spec`). Embute o `ControllerMachine.exe`
  já pronto (por isso builda depois dele), copia pra
  `C:\thenorian\controller` (escolhível), cria `logs/`, marca "iniciar com o
  Windows" por padrão (reaproveita `main.py --install-autostart`) e se
  autoexclui no final se marcado.
- **`ControllerMachine-linux.tar.gz`** — pacote Linux
  (`installer/build_linux_package.py`). Não compila nada — Linux roda o
  Python direto — só empacota o código headless (sem `gui/`, que é só do
  Windows) junto de `installer/linux/install.sh`. Rodar o `install.sh` de
  dentro do pacote: cria `~/.thenorian/controller` (escolhível), um `venv`
  isolado, instala as dependências e registra o serviço systemd (via
  `service_linux.py`, pede a senha por `sudo` só nessa hora — depois disso
  o systemd sobe sozinho a cada boot, sem senha nenhuma de novo).
