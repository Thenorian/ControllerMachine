"""
Modelagem orientada a objetos do modelo de impressão (layout do DANFE
NFC-e / NFe / Cupom) — pra usar do lado de quem embutir o `server/`
(Simple ERP ou qualquer outro sistema), junto com server.Server (ver
server.py). Isto é só um jeito mais confortável de
MONTAR o dict que Server.push_template()/ControllerConnector.send_template_update()
manda pela rede: o contrato que chega no Controller Machine continua sendo
o dict simples descrito em client/devices/printer_fiscal.py (DEFAULT_TEMPLATE)
— nada muda do lado de lá, `Template.to_dict()` só produz esse mesmo dict.

Duas formas de personalizar o layout:

1. Ajustar atributo direto, na instância que o Server já tem:

    server.template.NFCe.cabecalho.mostrar_ie = False
    server.template.NFCe.qr_code.module_size = 8

2. Herdar e sobrescrever comportamento (quando não é só um valor, é a
   própria regra de montagem que muda):

    class MinhaNFCe(NFCe):
        def to_dict(self):
            d = super().to_dict()
            d["mensagem_empresa"] = d["mensagem_empresa"].upper()
            return d

    server.template.NFCe = MinhaNFCe()

Em qualquer um dos dois casos, quem propaga a mudança pros controllers é
sempre `Server.push_template(...)` — nunca edição dispositivo por
dispositivo no Controller Machine (não existe editor de layout do lado do
client, de propósito).
"""
from __future__ import annotations


class Cabecalho:
    def __init__(self):
        self.texto_extra = ""      # linhas extras impressas antes do cabeçalho fixo (nome/CNPJ/endereço)
        self.mostrar_ie = True


class Rodape:
    def __init__(self):
        self.texto_extra = ""      # linhas extras impressas no final do documento


class QRCode:
    def __init__(self):
        self.module_size = 6
        self.error_correction = "M"    # L | M | Q | H


class MensagemEmpresa:
    def __init__(self):
        self.texto_padrao = ""     # usado só se a venda não trouxer mensagem_empresa própria (ver payload)


class Template:
    """Base — seções comuns a qualquer documento impresso. NFCe/NFe/Cupom
    herdam daqui; cada um ajusta só o que for de fato diferente pro seu
    tipo de documento."""

    titulo = "CUPOM - SEM VALOR FISCAL"

    def __init__(self):
        self.cabecalho = Cabecalho()
        self.rodape = Rodape()
        self.qr_code = QRCode()
        self.mensagem_empresa = MensagemEmpresa()
        self.blocos_customizados: list[dict] | None = None

    def to_dict(self) -> dict:
        """Serializa pro formato que client/devices/printer_fiscal.py lê em
        device["settings"]["template"] — é isso que Server.push_template()
        manda pela rede."""
        return {
            "header_text": self.cabecalho.texto_extra,
            "footer_text": self.rodape.texto_extra,
            "mostrar_ie": self.cabecalho.mostrar_ie,
            "mensagem_empresa": self.mensagem_empresa.texto_padrao,
            "qr_module_size": self.qr_code.module_size,
            "qr_error_correction": self.qr_code.error_correction,
            "cupom_titulo": self.titulo,
            "blocos_customizados": self.blocos_customizados,
        }


class NFCe(Template):
    """NFC-e — nota fiscal de consumidor eletrônica. QR Code, chave de
    acesso, protocolo e número/série são sempre fixos e vêm da VENDA (ver
    payload em printer_fiscal.py), nunca do template — aqui só entra o que
    de fato é configurável pra esse tipo de documento. blocos_customizados
    nunca é lido pra NFC-e (trava estrutural em render_danfe_nfce, não
    depende deste módulo se comportar bem)."""


class NFe(Template):
    """NFe — o Controller Machine hoje só sabe renderizar DANFE-NFCe de
    verdade (ver render_danfe_nfce); esta classe existe como ponto de
    extensão pro dia em que NFe entrar, sem prometer nenhum campo além dos
    da base."""


class Cupom(Template):
    """Cupom não fiscal — o único tipo que pode usar blocos_customizados
    (Modo Avançado: substitui o documento padrão por uma lista de blocos,
    ver TIPOS_BLOCO_VALIDOS em printer_fiscal.py)."""

    def usar_blocos_customizados(self, blocos: list[dict]) -> None:
        self.blocos_customizados = blocos

    def restaurar_layout_padrao(self) -> None:
        self.blocos_customizados = None


class TemplateSet:
    """`server.template` — namespace com um Template por tipo de
    documento. Cada atributo é uma instância (mutável) — trocar por uma
    subclasse inteira (`server.template.NFCe = MinhaNFCe()`) também vale."""

    def __init__(self):
        self.NFCe = NFCe()
        self.NFe = NFe()
        self.Cupom = Cupom()
