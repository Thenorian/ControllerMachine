"""
Builder mínimo de comandos ESC/POS — só o subconjunto padrão (init, texto,
alinhamento, negrito, corte) que praticamente toda impressora térmica de
cupom entende, independente de marca. Não é um driver completo: não cobre
código de barras, imagem ou comandos proprietários de fabricante — se
precisar disso no futuro, é aqui que entra.
"""
from __future__ import annotations

# Colunas de texto por linha, Font A (fonte padrão) — varia com a largura
# física da bobina. Números redondos usuais de mercado; se um equipamento
# específico imprimir com fonte diferente, ajustar aqui.
CHARS_PER_LINE = {40: 32, 80: 48}


def chars_per_line(paper_width_mm: int) -> int:
    try:
        return CHARS_PER_LINE[paper_width_mm]
    except KeyError:
        raise ValueError(
            f"largura de papel não suportada: {paper_width_mm}mm (use {sorted(CHARS_PER_LINE)})"
        )


ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"
ALIGN_LEFT = ESC + b"a" + b"\x00"
ALIGN_CENTER = ESC + b"a" + b"\x01"
ALIGN_RIGHT = ESC + b"a" + b"\x02"
BOLD_ON = ESC + b"E" + b"\x01"
BOLD_OFF = ESC + b"E" + b"\x00"
CUT = GS + b"V" + b"\x00"
LINE_FEED = b"\n"


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
        self._buffer += value.encode(self.encoding, errors="replace")
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

    def separator(self, char: str = "-", width: int = 42) -> "EscPosBuilder":
        return self.line(char * width)

    def feed(self, lines: int = 1) -> "EscPosBuilder":
        self._buffer += LINE_FEED * lines
        return self

    def cut(self) -> "EscPosBuilder":
        self._buffer += CUT
        return self

    def build(self) -> bytes:
        return bytes(self._buffer)
