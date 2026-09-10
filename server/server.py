"""
Server — fachada orientada a objetos em volta do ControllerConnector
(connector.py) + do TemplateSet (templates.py). Pensado como o ponto de
integração único do lado do Simple ERP: quem só precisa da ponte
(is_online, send_print_job...) pode continuar usando ControllerConnector
direto — nada nele muda —, mas quem também quer montar o modelo de
impressão de forma orientada a objetos usa Server, que expõe as duas
coisas juntas.

Uso típico dentro do Simple ERP:

    from server.server import Server

    server = Server(auth_check=check_auth)
    server.start()

    server.template.NFCe.cabecalho.mostrar_ie = False
    server.template.NFCe.qr_code.module_size = 8
    server.push_template(controller_id, device_id, "NFCe")

    # ou pra empresa inteira, sempre que a regra fiscal mudar:
    for controller_id in controllers_da_empresa(empresa_id):
        for device_id, info in server.list_devices(controller_id).items():
            if info["type"] == "printer_fiscal":
                server.push_template(controller_id, device_id, "NFCe")
"""
from __future__ import annotations

from connector import ControllerConnector
from templates import TemplateSet


class Server:
    def __init__(self, auth_check, host: str = "0.0.0.0", port: int = 7689, on_event=None):
        self.connector = ControllerConnector(auth_check, host=host, port=port, on_event=on_event)
        self.template = TemplateSet()

    # ------------------------------------------------------------------ #
    # Repassa pro ControllerConnector — Server não reimplementa nada de
    # transporte, só agrega.
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        self.connector.start()

    def stop(self) -> None:
        self.connector.stop()

    def is_online(self, controller_id: str, device_id: str | None = None) -> bool:
        return self.connector.is_online(controller_id, device_id)

    def list_devices(self, controller_id: str) -> dict:
        return self.connector.list_devices(controller_id)

    def list_online_controllers(self) -> list[str]:
        return self.connector.list_online_controllers()

    def send_print_job(self, controller_id: str, device_id: str, data_type: str, data_base64: str, timeout: float = 10) -> dict:
        return self.connector.send_print_job(controller_id, device_id, data_type, data_base64, timeout)

    def send_fiscal_job(self, controller_id: str, device_id: str, nfce_payload, timeout: float = 10, data_type: str | None = None) -> dict:
        return self.connector.send_fiscal_job(controller_id, device_id, nfce_payload, timeout, data_type)

    def send_scale_update(self, controller_id: str, device_id: str, products: list[dict], timeout: float = 15) -> dict:
        return self.connector.send_scale_update(controller_id, device_id, products, timeout)

    # ------------------------------------------------------------------ #
    # Ponto novo — usa o que estiver em self.template agora.
    # ------------------------------------------------------------------ #

    def push_template(self, controller_id: str, device_id: str, doc_type: str, timeout: float = 10) -> dict:
        """doc_type: "NFCe" | "NFe" | "Cupom" — nome do atributo em
        self.template. Serializa a instância atual (`.to_dict()`,
        respeitando qualquer override/subclasse trocada em self.template)
        e manda pelo mesmo canal de job que os outros send_*."""
        try:
            modelo = getattr(self.template, doc_type)
        except AttributeError:
            raise ValueError(f"doc_type inválido: {doc_type!r} (esperado NFCe, NFe ou Cupom)") from None
        return self.connector.send_template_update(controller_id, device_id, modelo.to_dict(), timeout=timeout)
