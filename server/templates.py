"""
Modelagem orientada a objetos do modelo de impressão (layout do DANFE
NFC-e / NFe / Cupom) — pra usar do lado de quem embutir o `server/`
(Simple ERP ou qualquer outro sistema), junto com server.Server (ver
server.py). Isto é só um jeito mais confortável de MONTAR o dict que
Server.push_template()/ControllerConnector.send_template_update() manda
pela rede: o contrato que chega no Controller Machine continua sendo o
dict simples descrito em client/devices/printer_fiscal.py (DEFAULT_TEMPLATE)
— nada muda do lado de lá, `Template.to_dict()` só produz esse mesmo dict.

Os componentes reutilizáveis (`Text`, `QRCode`) seguem o estilo dos widgets
do Tkinter — cria já com os valores prontos via construtor:

    NFCe(
        header=Text(text="Loja Centro — Rua das Flores, 123"),
        footer=Text(text="Volte sempre!"),
        mensagem_empresa=Text(text="Siga @lojacentro"),
        qr_code=QRCode(size=8),
        mostrar_ie=False,
        pdv_label="Caixa 1",
    )

— ou ajustando atributo por atributo depois de criado (`server.template.NFCe.qr_code.size = 8`).
`Text` só tem `bold`/`align` (não `fontsize`): impressora térmica ESC/POS
não tem fonte variável por trecho de texto, só um toggle de documento
inteiro (Font A/Font B — ver `fonte_pequena` abaixo, condensada por
padrão). `QRCode` não tem `value`: o conteúdo do QR é dado da VENDA (vem
no payload de cada nota, nunca do template — ver contrato em
printer_fiscal.py), só o module size/correção de erro são de fato
configuráveis aqui.

Pra manipulação mais fina (sublinhado, texto invertido, tamanho do
caractere, código de barras, pulso de gaveta de dinheiro, ou qualquer
comando ESC/POS crus que o Controller Machine não modele por nome — ver
`EscPosBuilder.raw()` no client) só o `Cupom` aceita, via
`blocos_customizados` — cada bloco é um dict simples, não um objeto desta
classe (ver TIPOS_BLOCO_VALIDOS em client/devices/printer_fiscal.py pro
vocabulário completo):

    server.template.Cupom.usar_blocos_customizados([
        {"tipo": "cabecalho"},
        {"tipo": "texto", "texto": "PROMOÇÃO", "negrito": True, "tamanho": [2, 2]},
        {"tipo": "codigo_barras", "dados": "789123456", "simbologia": "code128"},
        {"tipo": "itens"}, {"tipo": "totais"}, {"tipo": "pagamentos"},
        {"tipo": "abrir_gaveta"},
    ])

Segunda forma de personalizar, quando não é só um valor mas a própria
regra de montagem que muda — herdar e sobrescrever:

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


class Text:
    """Bloco de texto livre — cabeçalho, rodapé, mensagem da empresa.
    Aceita os placeholders {{campo}} e a repetição {"x"*N} (expandidos no
    Controller Machine no momento de imprimir, ver devices/template_text.py
    — lista de campos disponíveis em printer_fiscal.py::_contexto_template)."""

    def __init__(self, text: str = "", bold: bool = False, align: str = "left"):
        self.text = text
        self.bold = bold
        self.align = align


class QRCode:
    """Só a apresentação do QR Code — o conteúdo (URL) é dado da venda, não
    do template (ver docstring do módulo)."""

    def __init__(self, size: int = 6, error_correction: str = "M"):
        self.size = size
        self.error_correction = error_correction


class Template:
    """Base — campos comuns a qualquer documento impresso. NFCe/NFe/Cupom
    herdam daqui; cada um ajusta só o que for de fato diferente pro seu
    tipo de documento."""

    titulo = "CUPOM - SEM VALOR FISCAL"

    def __init__(self, header: Text | None = None, footer: Text | None = None,
                 mensagem_empresa: Text | None = None, qr_code: QRCode | None = None,
                 mostrar_ie: bool = True, pdv_label: str = "", fonte_pequena: bool = True,
                 blocos_customizados: list[dict] | None = None):
        self.header = header if header is not None else Text(align="center")
        self.footer = footer if footer is not None else Text(align="center")
        self.mensagem_empresa = mensagem_empresa if mensagem_empresa is not None else Text(align="left")
        self.qr_code = qr_code if qr_code is not None else QRCode()
        self.mostrar_ie = mostrar_ie
        self.pdv_label = pdv_label     # nome do caixa/PDV — nunca o nome do dispositivo de impressão
        self.fonte_pequena = fonte_pequena  # Font B (ESC/POS) — condensada por padrão, economiza bobina
        self.blocos_customizados = blocos_customizados

    def to_dict(self) -> dict:
        """Serializa pro formato que client/devices/printer_fiscal.py lê em
        device["settings"]["template"] — é isso que Server.push_template()
        manda pela rede."""
        return {
            "header_text": self.header.text,
            "header_bold": self.header.bold,
            "header_align": self.header.align,
            "footer_text": self.footer.text,
            "footer_bold": self.footer.bold,
            "footer_align": self.footer.align,
            "mostrar_ie": self.mostrar_ie,
            "mensagem_empresa": self.mensagem_empresa.text,
            "mensagem_empresa_bold": self.mensagem_empresa.bold,
            "mensagem_empresa_align": self.mensagem_empresa.align,
            "qr_module_size": self.qr_code.size,
            "qr_error_correction": self.qr_code.error_correction,
            "cupom_titulo": self.titulo,
            "pdv_label": self.pdv_label,
            "fonte_pequena": self.fonte_pequena,
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
