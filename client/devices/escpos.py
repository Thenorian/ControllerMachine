"""
Builder mínimo de comandos ESC/POS — só o subconjunto padrão (init, texto,
alinhamento, negrito, fonte, corte) que praticamente toda impressora térmica
de cupom entende, independente de marca. Não é um driver completo: não cobre
código de barras, imagem ou comandos proprietários de fabricante — se
precisar disso no futuro, é aqui que entra.
"""
from __future__ import annotations

import unicodedata

# Colunas de texto por linha — varia com a largura física da bobina E com a
# fonte selecionada (Font B é mais estreita/condensada, cabe mais caractere
# na mesma bobina). Números redondos usuais de mercado; se um equipamento
# específico imprimir com fonte diferente, ajustar aqui.
CHARS_PER_LINE = {58: 32, 80: 48}
CHARS_PER_LINE_FONT_B = {58: 42, 80: 64}


def chars_per_line(paper_width_mm: int, fonte_pequena: bool = False) -> int:
    tabela = CHARS_PER_LINE_FONT_B if fonte_pequena else CHARS_PER_LINE
    try:
        return tabela[paper_width_mm]
    except KeyError:
        raise ValueError(
            f"largura de papel não suportada: {paper_width_mm}mm (use {sorted(CHARS_PER_LINE)})"
        )


def to_ascii(value: str) -> str:
    """Transliteração pra ASCII puro (7 bits) — impressora térmica genérica
    nem sempre tem o codepage certo selecionado pro acento aparecer certo
    (varia por marca/firmware, e nem toda impressora aceita o comando de
    trocar codepage) - resultado sem isso é lixo no lugar de "ç"/"ã"/"é" etc.
    ASCII puro é idêntico em QUALQUER codepage, então normalizar aqui elimina
    o problema de vez, sem precisar acertar o codepage de cada equipamento.
    NFKD decompõe o acento da letra (ex.: "ç" -> "c" + cedilha combinante) e
    o encode/decode ascii descarta a parte que sobra."""
    normalizado = unicodedata.normalize("NFKD", value)
    return normalizado.encode("ascii", "ignore").decode("ascii")


ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"
ALIGN_LEFT = ESC + b"a" + b"\x00"
ALIGN_CENTER = ESC + b"a" + b"\x01"
ALIGN_RIGHT = ESC + b"a" + b"\x02"
BOLD_ON = ESC + b"E" + b"\x01"
BOLD_OFF = ESC + b"E" + b"\x00"
FONT_A = ESC + b"M" + b"\x00"  # fonte padrao (maior)
FONT_B = ESC + b"M" + b"\x01"  # fonte condensada (menor, mais estreita)
CUT_FULL = GS + b"V" + b"\x00"
CUT_PARTIAL = GS + b"V" + b"\x01"
LINE_FEED = b"\n"

QR_ERROR_LEVELS = {"L": 0x30, "M": 0x31, "Q": 0x32, "H": 0x33}


def format_brl(value: float) -> str:
    """Formata valor monetário no padrão exigido pelo Manual do DANFE NFC-e
    (Divisões II e III): vírgula decimal, ponto como separador de milhar —
    ex.: 1234.5 -> "1.234,50". Nunca usar f"{v:.2f}" puro num DANFE (isso dá
    "1234.50", fora do padrão)."""
    inteiro, decimal = f"{value:,.2f}".split(".")
    return f"{inteiro.replace(',', '.')},{decimal}"

# Encodings mais comuns em impressora térmica nacional — cp860 (padrão desse
# módulo) é o de fato mais usado no Brasil, os outros existem porque alguns
# equipamentos/firmwares mais novos ou importados esperam charset diferente.
SUPPORTED_ENCODINGS = ("cp860", "cp850", "cp437", "cp1252", "utf-8")


class EscPosBuilder:
    def __init__(self, encoding: str = "cp860", plain: bool = False):
        """plain=True: modo "raw" — não emite nenhum comando ESC/POS além do
        init/corte (sem negrito, sem alinhamento). Existe pra equipamento
        genérico/desconhecido que só entende texto puro e pode se confundir
        com sequências de controle que ele não reconhece."""
        self.encoding = encoding
        self.plain = plain
        self._buffer = bytearray(INIT)

    def text(self, value: str) -> "EscPosBuilder":
        # Sempre transliterado pra ASCII antes de encodar - ver to_ascii(),
        # elimina acento virando lixo sem depender do codepage certo estar
        # selecionado na impressora. errors="replace" aqui é só rede de
        # segurança pro raro caractere que sobrar fora do ASCII (símbolo,
        # emoji etc.) - nunca deveria disparar em texto de nota fiscal normal.
        self._buffer += to_ascii(value).encode(self.encoding, errors="replace")
        return self

    def line(self, value: str = "") -> "EscPosBuilder":
        self.text(value)
        self._buffer += LINE_FEED
        return self

    def align(self, where: str) -> "EscPosBuilder":
        if self.plain:
            return self
        self._buffer += {"left": ALIGN_LEFT, "center": ALIGN_CENTER, "right": ALIGN_RIGHT}[where]
        return self

    def bold(self, on: bool) -> "EscPosBuilder":
        if self.plain:
            return self
        self._buffer += BOLD_ON if on else BOLD_OFF
        return self

    def font(self, small: bool) -> "EscPosBuilder":
        """Font B (menor/condensada) em vez da Font A padrão - pedido pra
        caber mais informação na mesma bobina. Chamar uma vez logo no início
        do documento (ver render_danfe_nfce) - a impressora mantém a fonte
        selecionada até o próximo ESC M ou até desligar."""
        if self.plain:
            return self
        self._buffer += FONT_B if small else FONT_A
        return self

    def separator(self, char: str = "-", width: int = 42) -> "EscPosBuilder":
        return self.line(char * width)

    def qr_code(self, data: str, module_size: int = 6, error_correction: str = "M") -> "EscPosBuilder":
        """QR Code 2D real via GS ( k — extensão de fato criada pela Epson,
        hoje replicada pela maioria das impressoras térmicas nacionais
        (Bematech, Elgin, Daruma, Tanca etc.), não é parte formal do padrão
        ESC/POS. Referência: Manual de Especificações Técnicas do DANFE
        NFC-e e QR Code — módulo mínimo pra caber em 25mm x 25mm com a
        largura de bobina usada aqui é module_size=6 a 8, ajustar se algum
        equipamento específico imprimir grande/pequeno demais.

        Em modo plain (impressora genérica, texto puro) o comando binário
        não seria entendido — imprime a URL como texto em vez de travar
        a impressora com bytes que ela não reconhece."""
        if self.plain:
            return self.line(data)

        ec_level = QR_ERROR_LEVELS[error_correction]
        payload = data.encode("utf-8")
        length = len(payload) + 3
        pL, pH = length & 0xFF, (length >> 8) & 0xFF

        self._buffer += GS + b"(k" + bytes([4, 0]) + b"1A" + bytes([50, 0])  # modelo 2
        self._buffer += GS + b"(k" + bytes([3, 0]) + b"1C" + bytes([module_size])  # tamanho do módulo
        self._buffer += GS + b"(k" + bytes([3, 0]) + b"1E" + bytes([ec_level])  # correção de erro
        self._buffer += GS + b"(k" + bytes([pL, pH]) + b"1P0" + payload  # armazena os dados
        self._buffer += GS + b"(k" + bytes([3, 0]) + b"1Q0"  # imprime o símbolo armazenado
        self._buffer += LINE_FEED
        return self

    def feed(self, lines: int = 1) -> "EscPosBuilder":
        self._buffer += LINE_FEED * lines
        return self

    def cut(self, mode: str = "full") -> "EscPosBuilder":
        if mode == "full":
            self._buffer += CUT_FULL
        elif mode == "partial":
            self._buffer += CUT_PARTIAL
        elif mode == "none":
            pass
        else:
            raise ValueError(f"modo de corte desconhecido: {mode!r} (use full/partial/none)")
        return self

    def build(self) -> bytes:
        return bytes(self._buffer)
