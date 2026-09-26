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
EscPosBuilder: align/bold/font/line/separator/feed/cut/qr_code/build, mais
logo/qr_with_lines que só existem aqui de verdade - ver docstring de cada).
"""
from __future__ import annotations

import io
import logging
import os

from PIL import Image, ImageDraw, ImageFont
import qrcode
import qrcode.constants

from devices.escpos import INIT, CUT_FULL, CUT_PARTIAL, chars_per_line, to_ascii

logger = logging.getLogger("image_receipt")

FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONT_REGULAR_PATH = os.path.join(FONTS_DIR, "DejaVuSansMono.ttf")
FONT_BOLD_PATH = os.path.join(FONTS_DIR, "DejaVuSansMono-Bold.ttf")

# Dots de largura imprimível por bobina - números padrão de mercado pra
# impressora térmica a 203dpi (mesma ideia de escpos.py::CHARS_PER_LINE,
# mas em pixels em vez de colunas de texto). Ajustar aqui se algum
# equipamento específico usar uma resolução diferente.
PRINTABLE_DOTS = {58: 384, 80: 576}

# 203dpi (~8 dots/mm) - mesma resolução assumida em toda a Controller
# Machine pra impressora térmica (ver label_render.py::THERMAL_DPMM do lado
# do Simple ERP). Usado só pra converter as margens abaixo, que são
# pensadas em mm (unidade que faz sentido pra quem configura o leiaute),
# pro pixel de verdade que o Pillow desenha.
DOTS_PER_MM = 8

# Margens do cupom (pedido explícito, 2026-09-26): esquerda com mais respiro
# (a maioria das impressoras corta rente à esquerda sem isso), embaixo um
# pouco de sobra antes do feed de corte (ver render_danfe_nfce), em cima só
# o mínimo pra não desperdiçar bobina. Direita continua na razão antiga
# (MARGIN_RATIO) - nunca pedido pra mudar.
MARGIN_LEFT_MM = 3
MARGIN_TOP_MM = 3
MARGIN_BOTTOM_MM = 3
MARGIN_RATIO = 0.02    # margem direita = 2% da largura da bobina

_QR_ERROR_LEVELS = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}

LEADING_FACTOR = 1.25  # espaço entre linhas = altura da fonte * isso (~25% de respiro)

# QR Code + informações da SEFAZ lado a lado (pedido explícito, 2026-09-26 -
# "economiza papel e ajuda o planeta") - texto fica com a maior fatia da
# largura (informação costuma precisar de mais linhas que o QR precisa de
# largura), QR fica com o resto. Ver ImageReceiptBuilder.qr_with_lines.
QR_SIDE_TEXT_RATIO = 0.58
QR_SIDE_GAP_MM = 2

# Logo da empresa (pedido explícito, 2026-09-26): cabe num retângulo de até
# 6 linhas de altura (Fonte B) por toda a largura útil da bobina - qualquer
# imagem enviada pela empresa (proporção "quebrada" ou não) é encaixada
# nesse retângulo preservando a proporção original (nunca esticada/achatada
# - ver _build_logo_image). Sai sempre ACIMA da razão social (ver
# printer_fiscal.py::_cabecalho_emitente).
LOGO_MAX_LINES = 6


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
        self._margin_left = round(MARGIN_LEFT_MM * DOTS_PER_MM)
        self._margin_right = round(self.dots_width * MARGIN_RATIO)
        self._margin_top = round(MARGIN_TOP_MM * DOTS_PER_MM)
        self._margin_bottom = round(MARGIN_BOTTOM_MM * DOTS_PER_MM)
        self._content_width = self.dots_width - self._margin_left - self._margin_right

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

    def qr_with_lines(self, data: str, lines: list[str], module_size: int = 6,
                       error_correction: str = "M") -> "ImageReceiptBuilder":
        """QR Code à ESQUERDA, texto (ex.: chave de acesso, protocolo) à
        DIREITA, lado a lado na mesma altura - economiza papel na vertical
        em troca de uma faixa mais alta na horizontal (pedido explícito,
        2026-09-26). Cada string de `lines` é quebrada por palavra pra
        caber na coluna de texto (bem mais estreita que a largura cheia
        usada por .line()) - ver _wrap_text."""
        self.ops.append(("qr_side", data, error_correction, tuple(l for l in lines if l)))
        return self

    def logo(self, image_bytes: bytes | None) -> "ImageReceiptBuilder":
        """Logo da empresa, sempre centralizado, ANTES de qualquer outra
        coisa que já esteja na fila (chamar antes da razão social - ver
        printer_fiscal.py::_cabecalho_emitente). Encaixado num retângulo de
        LOGO_MAX_LINES linhas de altura por toda a largura útil, preservando
        a proporção original (nunca esticado/achatado - ver
        _build_logo_image). image_bytes=None ou imagem corrompida: vira
        no-op silencioso (nunca derruba a impressão do cupom por causa de
        um logo ruim)."""
        if image_bytes:
            self.ops.append(("logo", image_bytes))
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
        conteudo_altura = 0
        cache: dict[int, object] = {}
        for idx, op in enumerate(self.ops):
            if op[0] == "text":
                conteudo_altura += self._line_height(op[3])
            elif op[0] == "rule":
                conteudo_altura += self._line_height(True)
            elif op[0] == "feed":
                conteudo_altura += self._line_height(True) * op[1]
            elif op[0] == "qr":
                _, data, error_correction = op
                tamanho_alvo = round(self._content_width * 0.55)
                qr_img = _build_qr_image(data, error_correction, tamanho_alvo)
                cache[idx] = qr_img
                conteudo_altura += qr_img.height + self._line_height(True) // 2
            elif op[0] == "qr_side":
                _, data, error_correction, lines = op
                gap_px = round(QR_SIDE_GAP_MM * DOTS_PER_MM)
                texto_w = round(self._content_width * QR_SIDE_TEXT_RATIO)
                qr_w = max(1, self._content_width - texto_w - gap_px)
                qr_img = _build_qr_image(data, error_correction, qr_w)
                font = self._font_for(True, False)
                linhas_quebradas: list[str] = []
                for linha in lines:
                    linhas_quebradas.extend(_wrap_text(linha, font, texto_w))
                linha_h = self._line_height(True)
                texto_altura = linha_h * len(linhas_quebradas)
                bloco_altura = max(qr_img.height, texto_altura)
                cache[idx] = (qr_img, linhas_quebradas, gap_px)
                conteudo_altura += bloco_altura + linha_h // 2
            elif op[0] == "logo":
                _, image_bytes = op
                max_h = self._line_height(True) * LOGO_MAX_LINES
                logo_img = _build_logo_image(image_bytes, self._content_width, max_h)
                if logo_img is not None:
                    cache[idx] = logo_img
                    conteudo_altura += logo_img.height + self._line_height(True) // 2

        altura = max(self._margin_top + conteudo_altura + self._margin_bottom, 1)
        img = Image.new("L", (self.dots_width, altura), color=255)
        draw = ImageDraw.Draw(img)

        y = self._margin_top
        for idx, op in enumerate(self.ops):
            if op[0] == "text":
                _, text, align, small, bold = op
                font = self._font_for(small, bold)
                line_h = self._line_height(small)
                largura_texto = font.getlength(text)
                if align == "center":
                    x = self._margin_left + (self._content_width - largura_texto) / 2
                elif align == "right":
                    x = self._margin_left + self._content_width - largura_texto
                else:
                    x = self._margin_left
                draw.text((x, y), text, font=font, fill=0)
                y += line_h
            elif op[0] == "rule":
                line_h = self._line_height(True)
                meio = y + line_h // 2
                x0, x1 = self._margin_left, self.dots_width - self._margin_right
                if op[1] == "double":
                    draw.line([(x0, meio - 1), (x1, meio - 1)], fill=0, width=1)
                    draw.line([(x0, meio + 2), (x1, meio + 2)], fill=0, width=1)
                else:
                    draw.line([(x0, meio), (x1, meio)], fill=0, width=1)
                y += line_h
            elif op[0] == "feed":
                y += self._line_height(True) * op[1]
            elif op[0] == "qr":
                qr_img = cache[idx]
                x = self._margin_left + (self._content_width - qr_img.width) // 2
                img.paste(qr_img, (x, y))
                y += qr_img.height + self._line_height(True) // 2
            elif op[0] == "qr_side":
                qr_img, linhas_quebradas, gap_px = cache[idx]
                font = self._font_for(True, False)
                linha_h = self._line_height(True)
                texto_altura = linha_h * len(linhas_quebradas)
                bloco_altura = max(qr_img.height, texto_altura)
                qr_y = y + (bloco_altura - qr_img.height) // 2
                img.paste(qr_img, (self._margin_left, qr_y))
                texto_x = self._margin_left + qr_img.width + gap_px
                texto_y = y + (bloco_altura - texto_altura) // 2
                for i, linha in enumerate(linhas_quebradas):
                    draw.text((texto_x, texto_y + i * linha_h), linha, font=font, fill=0)
                y += bloco_altura + linha_h // 2
            elif op[0] == "logo":
                logo_img = cache.get(idx)
                if logo_img is not None:
                    x = self._margin_left + (self._content_width - logo_img.width) // 2
                    img.paste(logo_img, (x, y))
                    y += logo_img.height + self._line_height(True) // 2

        # Sem dithering: threshold puro (128) - dithering deixaria texto e
        # QR Code borrados/acinzentados (QR borrado pode nem ler no leitor).
        return img.point(lambda p: 0 if p < 128 else 255).convert("1")


def _build_qr_image(data: str, error_correction: str, tamanho_alvo_px: int) -> Image.Image:
    qr = qrcode.QRCode(
        error_correction=_QR_ERROR_LEVELS.get(error_correction, qrcode.constants.ERROR_CORRECT_M),
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("L")

    tamanho_alvo = max(1, tamanho_alvo_px)
    # NEAREST (não interpola) - qualquer suavização borra os módulos do QR
    # e pode deixar ele ilegível pro leitor.
    return img.resize((tamanho_alvo, tamanho_alvo), Image.NEAREST)


def _build_logo_image(image_bytes: bytes, max_width_px: int, max_height_px: int) -> Image.Image | None:
    """Encaixa a imagem do logo (qualquer formato/proporção que a empresa
    tenha enviado) dentro do retângulo max_width_px x max_height_px SEM
    esticar/achatar - escala preservando proporção (fator único pros dois
    eixos, o menor dos dois limites) e centraliza. Transparência vira fundo
    branco (nunca preto - papel térmico já É branco). Qualquer falha ao
    abrir a imagem (arquivo corrompido, formato não suportado) só loga e
    devolve None - um logo ruim nunca pode derrubar a impressão do cupom
    fiscal inteiro."""
    try:
        logo = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception:
        logger.warning("Logo da empresa não pôde ser decodificado - imprimindo cupom sem logo")
        return None

    fundo = Image.new("RGBA", logo.size, (255, 255, 255, 255))
    fundo.paste(logo, mask=logo.split()[3])
    logo_l = fundo.convert("L")

    escala = min(max_width_px / logo_l.width, max_height_px / logo_l.height)
    novo_w = max(1, round(logo_l.width * escala))
    novo_h = max(1, round(logo_l.height * escala))
    return logo_l.resize((novo_w, novo_h), Image.LANCZOS)


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
