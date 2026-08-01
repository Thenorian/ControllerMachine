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

from catalog import DeviceCatalog
from devices import printer_common, printer_fiscal
from devices.scale import get_formatter
from transport import ControllerTransport

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("main")


def handle_job(catalog: DeviceCatalog, job: dict) -> dict:
    kind = job.get("kind")
    device = catalog.get_device(job.get("device_id", ""))
    if device is None:
        return {"status": "error", "message": f"dispositivo desconhecido: {job.get('device_id')}"}

    try:
        if kind == "print":
            _dispatch_print(device, job)
        elif kind == "print_fiscal_nfce":
            _dispatch_fiscal(device, job)
        elif kind == "scale_update":
            _dispatch_scale(device, job)
        else:
            return {"status": "error", "message": f"kind desconhecido: {kind}"}
    except Exception as err:
        logger.exception(f"Falha executando job {kind} no device {device['label']}")
        return {"status": "error", "message": str(err)}

    return {"status": "done"}


def _dispatch_print(device: dict, job: dict) -> None:
    data = base64.b64decode(job["data"])
    connection = device["connection"]

    if job.get("data_type") == "pdf":
        printer_common.print_pdf(connection, data)
    elif connection["kind"] == "os_printer":
        printer_common.print_raw(connection, data)
    elif connection["kind"] == "tcp":
        printer_common.print_via_tcp(connection, data)
    else:
        raise ValueError(f"conexão não suportada para impressão: {connection}")


def _dispatch_fiscal(device: dict, job: dict) -> None:
    connection = device["connection"]
    is_pdf = job.get("data_type") == "pdf"

    if is_pdf:
        # Simple ERP (ou o provedor de NFC-e) já manda o DANFE pronto em
        # PDF — não tem o que renderizar aqui, só entregar.
        data = base64.b64decode(job["data"])
    else:
        settings = device.get("settings", {})
        data = printer_fiscal.render_danfe_nfce(
            job["data"],
            paper_width_mm=settings.get("paper_width_mm", 80),
            mode=settings.get("mode", "escpos"),
        )

    if connection["kind"] == "pdf_folder":
        if not is_pdf:
            raise ValueError("connection kind 'pdf_folder' exige job com data_type='pdf'")
        printer_common.save_pdf_to_folder(connection, data, name_hint=job.get("job_id"))
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


def run_windows(catalog: DeviceCatalog, transport: ControllerTransport) -> None:
    from gui.tray import HAS_TRAY, install_windows_autostart, run_tray
    from gui.window import ControllerWindow

    if "--install-autostart" in sys.argv:
        install_windows_autostart(str(__import__("pathlib").Path(__file__).resolve()))
        return

    transport.start()
    window = ControllerWindow(catalog, transport)

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
    transport = ControllerTransport(
        host=catalog.connector_host,
        port=catalog.connector_port,
        controller_id=catalog.controller_id,
        secret=catalog.secret,
        announce_payload=catalog.to_announce_payload,
        on_job=lambda job: handle_job(catalog, job),
    )

    system = platform.system()
    if system == "Windows":
        run_windows(catalog, transport)
    elif system == "Linux":
        run_linux(catalog, transport)
    else:
        logger.error(f"Sistema operacional não suportado: {system}")
        sys.exit(1)


if __name__ == "__main__":
    main()
