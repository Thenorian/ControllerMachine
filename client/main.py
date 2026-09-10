"""
Controller Machine — ponto de entrada.

Windows: abre com ícone na bandeja (janela começa escondida se já estiver
configurado; aparece se for a primeira execução).

Linux: sem GUI. `python main.py --install-service` registra e sobe como
serviço systemd (precisa de sudo). Rodando direto (sem esse flag), funciona
em primeiro plano — útil para debug ou pra quem preferir gerenciar o
processo de outro jeito (supervisord, docker, etc.).
"""
from __future__ import annotations

import base64
import logging
import platform
import sys

import print_history
from catalog import DeviceCatalog
from devices import printer_common, printer_fiscal, printer_cash
from devices.scale import get_formatter
from logging_setup import setup_logging
from transport import ControllerTransport

setup_logging()
logger = logging.getLogger("main")


# Descrição amigável de cada job pro log de texto (arquivo em logs/ e aba
# "Log" na janela) — pedido pra dar visibilidade tipo "[data/hora] Impresso
# documento fiscal NFC-e", "Comunicação com a balança" etc. sem precisar
# abrir o histórico (aba "Histórico"/print_history.db) pra saber o que
# aconteceu. `%(asctime)s` do próprio logging já cobre a parte de data/hora
# (ver logging_setup.py), aqui só monta o texto.
_DESCRICAO_JOB = {
    "print": "Impressão comum",
    "scale_update": "Comunicação com a balança",
}
_DESCRICAO_FISCAL = {
    "nfce": "Impressão de documento fiscal NFC-e",
    "cupom": "Impressão de cupom (sem valor fiscal)",
    "caixa": "Impressão de cupom de caixa (abertura/fechamento)",
}
JOBS_RASTREADOS = {"print", "print_fiscal_nfce", "scale_update"}


def handle_job(catalog: DeviceCatalog, job: dict, ask_folder=None) -> dict:
    """ask_folder: callable(title: str) -> str | None, opcional — usado só
    por dispositivo (fiscal ou comum) configurado como "perguntar a pasta a
    cada impressão" (ver DeviceDialog em gui/window.py). None quando não há
    GUI disponível pra perguntar nada (ex.: Linux headless)."""
    kind = job.get("kind")
    device = catalog.get_device(job.get("device_id", ""))
    if device is None:
        return {"status": "error", "message": f"dispositivo desconhecido: {job.get('device_id')}"}

    rastreado = kind in JOBS_RASTREADOS
    descricao = _descricao_job(kind, job) if rastreado else None

    try:
        if kind == "print":
            _dispatch_print(device, job, ask_folder)
        elif kind == "print_fiscal_nfce":
            _dispatch_fiscal(device, job, ask_folder)
        elif kind == "scale_update":
            _dispatch_scale(device, job)
        elif kind == "set_template":
            catalog.set_device_template(device["device_id"], job.get("template") or {})
        else:
            return {"status": "error", "message": f"kind desconhecido: {kind}"}
    except Exception as err:
        logger.exception(f"Falha executando job {kind} no device {device['label']}")
        if rastreado:
            logger.warning(f"{descricao} FALHOU — {device['label']}: {err}")
            print_history.registrar(
                device["device_id"], device["label"], kind, _job_tipo_documento(kind, job),
                sucesso=False, mensagem=str(err),
            )
        return {"status": "error", "message": str(err)}

    if rastreado:
        logger.info(f"{descricao} — {device['label']}")
        print_history.registrar(
            device["device_id"], device["label"], kind, _job_tipo_documento(kind, job), sucesso=True,
        )
    return {"status": "done"}


def _descricao_job(kind: str, job: dict) -> str:
    if kind == "print_fiscal_nfce":
        if job.get("data_type") == "pdf":
            return "Impressão de DANFE (PDF já pronto)"
        tipo_doc = (job.get("data") or {}).get("tipo_documento", "nfce")
        return _DESCRICAO_FISCAL.get(tipo_doc, "Impressão fiscal")
    return _DESCRICAO_JOB.get(kind, kind)


def _job_tipo_documento(kind: str, job: dict) -> str | None:
    """"nfce"/"cupom"/"caixa" pro job fiscal (vem do próprio payload da
    venda) — None pra impressão comum/balança (não carregam esse conceito)
    e pro fiscal já vindo pronto em PDF (job["data"] é base64, não o
    payload)."""
    if kind != "print_fiscal_nfce" or job.get("data_type") == "pdf":
        return None
    return (job.get("data") or {}).get("tipo_documento")


def _dispatch_print(device: dict, job: dict, ask_folder=None) -> None:
    data = base64.b64decode(job["data"])
    connection = device["connection"]
    is_pdf = job.get("data_type") == "pdf"

    if connection["kind"] == "pdf_folder":
        if not is_pdf:
            raise ValueError("connection kind 'pdf_folder' exige job com data_type='pdf'")
        _salvar_pdf_em_pasta(device, connection, data, job.get("job_id"), ask_folder)
    elif is_pdf:
        printer_common.print_pdf(connection, data)
    elif connection["kind"] == "os_printer":
        printer_common.print_raw(connection, data)
    elif connection["kind"] == "tcp":
        printer_common.print_via_tcp(connection, data)
    else:
        raise ValueError(f"conexão não suportada para impressão: {connection}")


def _salvar_pdf_em_pasta(device: dict, connection: dict, data: bytes, job_id: str | None, ask_folder=None) -> None:
    """Compartilhado por impressão comum e fiscal — connection kind
    "pdf_folder" nos dois casos. Existe pra quem quer salvar o PDF em disco
    em vez de imprimir de fato (ex.: alternativa a apontar pra um driver
    virtual como "Microsoft Print to PDF", que sempre abre uma caixa de
    diálogo pra escolher onde salvar — aqui é automático)."""
    path = connection.get("path")
    if connection.get("ask_each_time") or not path:
        if ask_folder is None:
            raise RuntimeError(
                "dispositivo configurado para perguntar a pasta a cada impressão, "
                "mas a interface gráfica não está disponível pra perguntar"
            )
        path = ask_folder(f"Salvar PDF — {device['label']}")
        if not path:
            raise RuntimeError("operador não escolheu pasta — PDF não foi salvo")

    printer_common.save_pdf_to_folder({"path": path}, data, name_hint=job_id)


def _dispatch_fiscal(device: dict, job: dict, ask_folder=None) -> None:
    connection = device["connection"]
    is_pdf = job.get("data_type") == "pdf"

    if is_pdf:
        # Simple ERP (ou o provedor de NFC-e) já manda o DANFE pronto em
        # PDF — não tem o que renderizar aqui, só entregar.
        data = base64.b64decode(job["data"])
    elif (job.get("data") or {}).get("tipo_documento") == "caixa":
        # Cupom de abertura/fechamento de caixa - documento interno, nunca
        # fiscal, renderer isolado do fluxo de nota (ver devices/printer_cash.py).
        settings = device.get("settings", {})
        data = printer_cash.render_cupom_caixa(
            job["data"],
            paper_width_mm=settings.get("paper_width_mm", 80),
            mode=settings.get("mode", "escpos"),
            encoding=settings.get("encoding", "cp860"),
            cut_mode=settings.get("cut_mode", "full"),
        )
    else:
        settings = device.get("settings", {})
        template = dict(settings.get("template") or {})
        # Compat: header_text/footer_text viviam soltos em settings antes do
        # editor de modelo existir — se o template novo não trouxer esses
        # campos, cai pros antigos, pra não apagar config de quem já tinha.
        template.setdefault("header_text", settings.get("header_text", ""))
        template.setdefault("footer_text", settings.get("footer_text", ""))
        data = printer_fiscal.render_danfe_nfce(
            job["data"],
            paper_width_mm=settings.get("paper_width_mm", 80),
            mode=settings.get("mode", "escpos"),
            encoding=settings.get("encoding", "cp860"),
            cut_mode=settings.get("cut_mode", "full"),
            template=template,
        )

    if connection["kind"] == "pdf_folder":
        if not is_pdf:
            raise ValueError("connection kind 'pdf_folder' exige job com data_type='pdf'")
        _salvar_pdf_em_pasta(device, connection, data, job.get("job_id"), ask_folder)
    elif connection["kind"] == "os_printer":
        if is_pdf:
            printer_common.print_pdf(connection, data)
        else:
            printer_common.print_raw(connection, data)
    elif connection["kind"] == "tcp":
        printer_common.print_via_tcp(connection, data)
    else:
        raise ValueError(f"conexão não suportada para impressão fiscal: {connection}")


def _dispatch_scale(device: dict, job: dict) -> None:
    formatter = get_formatter(device["brand"])
    table = formatter.build_table(job["products"])
    connection = device["connection"]

    if connection["kind"] == "tcp":
        import socket
        with socket.create_connection((connection["host"], connection["port"]), timeout=15) as sock:
            sock.sendall(table)
    elif connection["kind"] == "serial":
        import serial
        with serial.Serial(connection["serial_port"], connection.get("baudrate", 9600), timeout=15) as ser:
            ser.write(table)
    elif connection["kind"] == "file":
        # Balanças que importam a tabela de produtos de um arquivo (ex.:
        # Toledo Prix/MGV5, Ramuza/Atena) — path costuma ser uma pasta local
        # ou um compartilhamento de rede que o equipamento fica observando.
        # Grava num arquivo temporário no mesmo diretório e troca de nome no
        # final (os.replace é atômico) pra nunca deixar a balança ler o
        # arquivo pela metade.
        import os
        path = connection["path"]
        tmp_path = path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(table)
        os.replace(tmp_path, path)
    else:
        raise ValueError(f"conexão não suportada para balança: {connection}")


def run_linux(catalog: DeviceCatalog, transport: ControllerTransport) -> None:
    import service_linux

    if "--install-service" in sys.argv:
        entrypoint = str(__import__("pathlib").Path(__file__).resolve())
        service_linux.install_and_start(entrypoint)
        return

    if "--uninstall-service" in sys.argv:
        service_linux.uninstall()
        return

    transport.start()
    logger.info(
        "Rodando em primeiro plano. Para instalar como serviço systemd: "
        "python main.py --install-service"
    )
    try:
        while True:
            __import__("time").sleep(3600)
    except KeyboardInterrupt:
        transport.stop()


def run_windows(catalog: DeviceCatalog, transport: ControllerTransport, ask_folder_holder: dict) -> None:
    from gui.tray import HAS_TRAY, install_windows_autostart, run_tray
    from gui.window import ControllerWindow

    if "--install-autostart" in sys.argv:
        install_windows_autostart(str(__import__("pathlib").Path(__file__).resolve()))
        return

    transport.start()
    window = ControllerWindow(catalog, transport)
    ask_folder_holder["fn"] = window.folder_prompt.ask_folder

    if HAS_TRAY:
        run_tray(window)
        window.protocol("WM_DELETE_WINDOW", window.withdraw)  # fecha pra bandeja, não encerra
        if catalog.list_devices():
            window.withdraw()  # já configurado — some pra bandeja, acessível pelo ícone
    else:
        window.protocol("WM_DELETE_WINDOW", lambda: (transport.stop(), window.destroy()))

    window.mainloop()


def main() -> None:
    catalog = DeviceCatalog()
    # Preenchido só depois que a janela existir (run_windows) — em Linux
    # (sem GUI) fica None pra sempre, handle_job trata isso.
    ask_folder_holder: dict = {"fn": None}
    transport = ControllerTransport(
        host=catalog.connector_host,
        port=catalog.connector_port,
        controller_id=catalog.controller_id,
        secret=catalog.secret,
        announce_payload=catalog.to_announce_payload,
        on_job=lambda job: handle_job(catalog, job, ask_folder_holder["fn"]),
    )

    system = platform.system()
    if system == "Windows":
        run_windows(catalog, transport, ask_folder_holder)
    elif system == "Linux":
        run_linux(catalog, transport)
    else:
        logger.error(f"Sistema operacional não suportado: {system}")
        sys.exit(1)


if __name__ == "__main__":
    main()
