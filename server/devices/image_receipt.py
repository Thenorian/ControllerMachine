"""
Cópia de ControllerMachine/server/devices/image_receipt.py — mesma lógica de
sincronização de connector.py/templates.py/escpos.py/printer_fiscal.py (ver
docstring deles). Qualquer ajuste é feito no ControllerMachine e sincronizado
pra cá, nunca editado só aqui.

Renderiza o cupom como IMAGEM (bitmap) em vez de mandar a impressora montar
o texto com a fonte/entrelinha/QR Code dela própria. Existe porque o modo
"escpos" antigo (fonte B + ESC 3 n + GS ( k pro QR) depende de CADA
impressora/driver interpretar esses comandos do jeito certo - na prática,
isso quebra ("fonte cagada", linhas erradas) em algumas combinações de
impressora/driver que dizem suportar ESC/POS mas não implementam tudo igual
(caso real relatado por cliente, 2026-09-21, impressora Epson via driver
USB do Windows). Imprimir um bitmap pronto é o jeito mais universal que
existe em impressora térmica (GS v 0 é o comando mais básico/antigo do
protocolo) - a impressora não interpreta fonte nem QR nenhum, só carimba os
pontos preto/branco que a gente já decidiu aqui. "o que a gente vê é o que
sai", igual sistema de concorrente costuma fazer.

Trade-off consciente: imagem manda mais dado que texto puro (bitmap vs.
comando compacto) - impressora pode demorar um pouco mais pra imprimir.
Vale a troca por confiabilidade num documento fiscal.

Reusa o MESMO desenho de leiaute de printer_fiscal.py (_cabecalho_emitente,
_tabela_itens etc. continuam idênticas, geram texto com padding de coluna
fixo) - só troca o "builder" que recebe os comandos: em vez de bytes
ESC/POS de texto, este aqui acumula operações de desenho e rasteriza tudo
no final (ver ImageReceiptBuilder, mesma interface pública do
EscPosBuilder: align/bold/font/line/separator/feed/cut/qr_code/build).
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont
import qrcode
import qrcode.constants

from devices.escpos import INIT, CUT_FULL, CUT_PARTIAL, chars_per_line, to_ascii

FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONT_REGULAR_PATH = os.path.join(FONTS_DIR, "DejaVuSansMono.ttf")
FONT_BOLD_PATH = os.path.join(FONTS_DIR, "DejaVuSansMono-Bold.ttf")

# Dots de largura imprimível por bobina - números padrão de mercado pra
# impressora térmica a 203dpi (mesma ideia de escpos.py::CHARS_PER_LINE,
# mas em pixels em vez de colunas de texto). Ajustar aqui se algum
# equipamento específico usar uma resolução diferente.
PRINTABLE_DOTS = {58: 384, 80: 576}

_QR_ERROR_LEVELS = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}

LEADING_FACTOR = 1.25  # espaço entre linhas = altura da fonte * isso (~25% de respiro)
MARGIN_RATIO = 0.02    # margem esquerda/direita = 2% da largura da bobina


def _wrap_text(texto: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    """Quebra por palavra (nunca corta uma palavra ao meio) pra caber em
    max_width pixels - ver chamada em ImageReceiptBuilder.line() pro
    motivo (linha que não pode ser truncada, tipo a chave de acesso)."""
    if not texto:
        return [""]
    if font.getlength(texto) <= max_width:
        return [texto]

    linhas: list[str] = []
    linha_atual = ""
    for palavra in texto.split(" "):
        candidata = f"{linha_atual} {palavra}".strip()
        if font.getlength(candidata) <= max_width:
            linha_atual = candidata
            continue
        if linha_atual:
            linhas.append(linha_atual)
        if font.getlength(palavra) > max_width:
            # Palavra sozinha mais larga que a linha toda - só acontece com
            # string sem espaço nenhum (raro) - corta por caractere mesmo,
            # último recurso pra nunca estourar a borda do papel.
            while font.getlength(palavra) > max_width and len(palavra) > 1:
                corte = len(palavra)
                while corte > 1 and font.getlength(palavra[:corte]) > max_width:
                    corte -= 1
                linhas.append(palavra[:corte])
                palavra = palavra[corte:]
        linha_atual = palavra
    if linha_atual:
        linhas.append(linha_atual)
    return linhas


def printable_dots(paper_width_mm: int) -> int:
    try:
        return PRINTABLE_DOTS[paper_width_mm]
    except KeyError:
        raise ValueError(
            f"largura de papel não suportada: {paper_width_mm}mm (use {sorted(PRINTABLE_DOTS)})"
        )


def _fitted_font(path: str, target_width_px: float, num_chars: int, guess: int = 24) -> ImageFont.FreeTypeFont:
    """Acha o tamanho de fonte (monoespaçada) em que `num_chars` caracteres
    cabem em `target_width_px` - mede uma vez num tamanho qualquer e escala
    linearmente (fonte monoespaçada cresce linear, não precisa de busca
    iterativa pesada). `int()` (trunca pra baixo) em vez de `round()` de
    propósito - arredondar pra cima passava do teto de largura em bobinas
    estreitas (58mm: tamanho "exato" calculado em ~14.6pt, round() virava
    15pt e a linha estourava a margem, cortando texto/QR na borda - bug
    real, 2026-09-21). O laço abaixo é só uma rede de segurança pra
    qualquer resíduo de hinting da fonte que o cálculo linear não capture -
    normalmente não itera nem uma vez."""
    probe = ImageFont.truetype(path, guess)
    largura_medida = probe.getlength("0" * num_chars)
    tamanho = max(6, int(guess * target_width_px / largura_medida))
    fonte = ImageFont.truetype(path, tamanho)
    while tamanho > 6 and fonte.getlength("0" * num_chars) > target_width_px:
        tamanho -= 1
        fonte = ImageFont.truetype(path, tamanho)
    return fonte


class ImageReceiptBuilder:
    """Mesma interface pública do EscPosBuilder (ver escpos.py) - só
    acumula operações de desenho em vez de bytes ESC/POS de texto; a
    rasterização de verdade acontece em build()."""

    def __init__(self, paper_width_mm: int = 80, encoding: str | None = None, plain: bool = False):
        self.dots_width = printable_dots(paper_width_mm)
        margin = round(self.dots_width * MARGIN_RATIO)
        self._content_width = self.dots_width - 2 * margin
        self._margin = margin

        chars_b = chars_per_line(paper_width_mm, fonte_pequena=True)
        chars_a = chars_per_line(paper_width_mm, fonte_pequena=False)
        self._font_b = _fitted_font(FONT_REGULAR_PATH, self._content_width, chars_b)
        self._font_b_bold = _fitted_font(FONT_BOLD_PATH, self._content_width, chars_b)
        self._font_a = _fitted_font(FONT_REGULAR_PATH, self._content_width, chars_a)
        self._font_a_bold = _fitted_font(FONT_BOLD_PATH, self._content_width, chars_a)

        self._align = "left"
        self._bold = False
        self._small = True
        self._cut_mode: str | None = None
        self.ops: list[tuple] = []

    # --- mesma interface do EscPosBuilder --------------------------------
    def align(self, where: str) -> "ImageReceiptBuilder":
        self._align = where
        return self

    def bold(self, on: bool) -> "ImageReceiptBuilder":
        self._bold = on
        return self

    def font(self, small: bool) -> "ImageReceiptBuilder":
        self._small = small
        return self

    def line_spacing(self, dots: int | None = None) -> "ImageReceiptBuilder":
        return self  # a imagem controla a própria entrelinha (LEADING_FACTOR)

    def line(self, value: str = "") -> "ImageReceiptBuilder":
        # A imensa maioria das chamadas já vem fatiada certinho pelas
        # funções de leiaute (ex.: _cabecalho_emitente corta em
        # [:larguras.b]) - mas pelo menos uma (a chave de acesso de 44
        # dígitos, em _bloco_fiscal_e_qr) NUNCA pode ser cortada (violaria
        # o leiaute oficial do DANFE) e conta com o auto-wrap que toda
        # impressora térmica faz sozinha quando o texto passa da coluna.
        # Bitmap não tem esse auto-wrap de graça - _wrap_text reproduz o
        # mesmo comportamento (quebra por palavra) medindo pixel de
        # verdade, senão a linha estourava a borda do papel (bug real,
        # 2026-09-21, achado testando bobina de 58mm).
        font = self._font_for(self._small, self._bold)
        for pedaco in _wrap_text(to_ascii(value), font, self._content_width):
            self.ops.append(("text", pedaco, self._align, self._small, self._bold))
        return self

    def separator(self, char: str = "-", width: int = 42) -> "ImageReceiptBuilder":
        self.ops.append(("rule", "double" if char == "=" else "single"))
        return self

    def feed(self, lines: int = 1) -> "ImageReceiptBuilder":
        self.ops.append(("feed", lines))
        return self

    def cut(self, mode: str = "full") -> "ImageReceiptBuilder":
        self._cut_mode = mode
        return self

    def qr_code(self, data: str, module_size: int = 6, error_correction: str = "M") -> "ImageReceiptBuilder":
        self.ops.append(("qr", data, error_correction))
        return self

    def underline(self, on: bool) -> "ImageReceiptBuilder":
        return self  # não usado no leiaute de NFC-e atual

    def invert(self, on: bool) -> "ImageReceiptBuilder":
        return self  # idem

    # --- rasterização ------------------------------------------------------
    def _font_for(self, small: bool, bold: bool) -> ImageFont.FreeTypeFont:
        if small:
            return self._font_b_bold if bold else self._font_b
        return self._font_a_bold if bold else self._font_a

    def _line_height(self, small: bool) -> int:
        font = self._font_for(small, bold=False)
        ascent, descent = font.getmetrics()
        return round((ascent + descent) * LEADING_FACTOR)

    def build(self) -> bytes:
        img = self._render_image()
        raster = image_to_escpos_raster(img)
        result = bytearray(INIT)
        result += raster
        if self._cut_mode == "full":
            result += CUT_FULL
        elif self._cut_mode == "partial":
            result += CUT_PARTIAL
        return bytes(result)

    def _render_image(self) -> Image.Image:
        # 1a passada: só mede a altura total (sem desenhar nada ainda).
        altura = 0
        qr_cache: dict[int, Image.Image] = {}
        for idx, op in enumerate(self.ops):
            if op[0] == "text":
                altura += self._line_height(op[3])
            elif op[0] == "rule":
                altura += self._line_height(True)
            elif op[0] == "feed":
                altura += self._line_height(True) * op[1]
            elif op[0] == "qr":
                _, data, error_correction = op
                qr_img = _build_qr_image(data, error_correction, self._content_width)
                qr_cache[idx] = qr_img
                altura += qr_img.height + self._line_height(True) // 2

        altura = max(altura, 1)
        img = Image.new("L", (self.dots_width, altura), color=255)
        draw = ImageDraw.Draw(img)

        y = 0
        for idx, op in enumerate(self.ops):
            if op[0] == "text":
                _, text, align, small, bold = op
                font = self._font_for(small, bold)
                line_h = self._line_height(small)
                largura_texto = font.getlength(text)
                if align == "center":
                    x = self._margin + (self._content_width - largura_texto) / 2
                elif align == "right":
                    x = self._margin + self._content_width - largura_texto
                else:
                    x = self._margin
                draw.text((x, y), text, font=font, fill=0)
                y += line_h
            elif op[0] == "rule":
                line_h = self._line_height(True)
                meio = y + line_h // 2
                if op[1] == "double":
                    draw.line([(self._margin, meio - 1), (self.dots_width - self._margin, meio - 1)], fill=0, width=1)
                    draw.line([(self._margin, meio + 2), (self.dots_width - self._margin, meio + 2)], fill=0, width=1)
                else:
                    draw.line([(self._margin, meio), (self.dots_width - self._margin, meio)], fill=0, width=1)
                y += line_h
            elif op[0] == "feed":
                y += self._line_height(True) * op[1]
            elif op[0] == "qr":
                qr_img = qr_cache[idx]
                x = (self.dots_width - qr_img.width) // 2
                img.paste(qr_img, (x, y))
                y += qr_img.height + self._line_height(True) // 2

        # Sem dithering: threshold puro (128) - dithering deixaria texto e
        # QR Code borrados/acinzentados (QR borrado pode nem ler no leitor).
        return img.point(lambda p: 0 if p < 128 else 255).convert("1")


def _build_qr_image(data: str, error_correction: str, content_width_px: int) -> Image.Image:
    qr = qrcode.QRCode(
        error_correction=_QR_ERROR_LEVELS.get(error_correction, qrcode.constants.ERROR_CORRECT_M),
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("L")

    # ~55% da largura da bobina - grande o bastante pra leitor de celular
    # sem exagerar (mesmo espírito do qr_module_size=5 do modo escpos antigo).
    tamanho_alvo = round(content_width_px * 0.55)
    # NEAREST (não interpola) - qualquer suavização borra os módulos do QR
    # e pode deixar ele ilegível pro leitor.
    return img.resize((tamanho_alvo, tamanho_alvo), Image.NEAREST)


def image_to_escpos_raster(img: Image.Image, chunk_height: int = 200) -> bytes:
    """GS v 0 (ESC/POS raster bit image) - comando mais básico/universal de
    impressão de imagem térmica, praticamente toda impressora ESC/POS
    entende (mais antigo e mais suportado que a fonte B ou o QR Code
    nativo GS ( k, que são extensões mais novas nem sempre implementadas
    igual em toda marca/clone). Manda em pedaços de `chunk_height` linhas
    pra não estourar o buffer de recebimento de impressoras mais simples
    com um comando gigante só."""
    width, height = img.size
    width_bytes = (width + 7) // 8
    raw = img.tobytes()  # modo "1": 1 byte por pixel (0 ou 255) nessa versão do Pillow ao usar tobytes? ver nota abaixo

    # Image.tobytes() em modo "1" já empacota 8 pixels por byte (MSB
    # primeiro), 0=preto/1=branco - GS v 0 espera o oposto (bit 1 = ponto
    # impresso/preto), por isso o "~" (inverte todos os bits) abaixo.
    linha_bytes = width_bytes
    esperado = linha_bytes * height
    if len(raw) != esperado:
        raise ValueError(f"empacotamento de imagem inesperado: {len(raw)} bytes, esperava {esperado}")

    dados = bytes((~b) & 0xFF for b in raw)

    saida = bytearray()
    for topo in range(0, height, chunk_height):
        bloco_altura = min(chunk_height, height - topo)
        bloco = dados[topo * linha_bytes: (topo + bloco_altura) * linha_bytes]
        xL, xH = width_bytes & 0xFF, (width_bytes >> 8) & 0xFF
        yL, yH = bloco_altura & 0xFF, (bloco_altura >> 8) & 0xFF
        saida += b"\x1d\x76\x30\x00" + bytes([xL, xH, yL, yH]) + bloco
    return bytes(saida)
