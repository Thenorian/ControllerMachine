"""
Balança Ramuza (linha Atena), carga por arquivo TXT.

O software da Ramuza no computador da loja (TM-xA Management Program) lê
esse TXT e manda os itens para a balança pela rede. Era assim que o sistema
antigo do cliente (aviário) trabalhava, e o layout abaixo foi tirado
desse arquivo real: `Exemplos Balança/TxitensrRAMUZA(ATENA 1 UTF-8).txt`.

Use com a conexão "file" do dispositivo (ver main.py::_dispatch_scale),
apontando para o arquivo que o software da Ramuza está configurado para ler.

LAYOUT (conferido nas 146 linhas do exemplo, comparando com o arquivo MGV5
dos mesmos produtos, cujo layout já é confirmado):

    posição  tamanho  campo
    0        4        PLU (ex.: "0047")
    4        2        2 últimos dígitos do PLU (ex.: "47")
    6        6        código do item, igual ao PLU (ex.: "000047")
    12       6        preço em centavos (ex.: "001390" = R$ 13,90)
    18       4        validade em dias (ex.: "0365")
    22       13       espaços
    35       5        "00000"
    40       ...      NOME##TEXTO1##TEXTO2##

    NOME   = primeiros 25 caracteres da descrição (nome na tela da balança)
    TEXTO1 = primeiros 25 caracteres da descrição (linha 1 da etiqueta)
    TEXTO2 = caracteres 26 a 50 (linha 2 da etiqueta, vazia se não precisar)
    Espaço que sobrar nas pontas de cada corte é removido.

Cada linha termina com TAB + quebra de linha (LF). O arquivo é UTF-8 com BOM.
A última linha é um terminador: PLU = maior PLU + 1, tudo zerado e
descrição vazia ("######").

O que não deu pra confirmar só pelo exemplo:
- Os 2 dígitos da posição 4: em 145 das 146 linhas são os 2 últimos dígitos
  do PLU. A única diferente é a primeira (PLU 2 com "39"), provavelmente
  algum ajuste manual no sistema antigo. Usamos sempre os 2 últimos dígitos.
- Os 13 espaços e o "00000" aparecem iguais em todas as linhas e são
  mantidos fixos.

A descrição vai em maiúsculas e sem acento, igual ao exemplo, porque a
fonte da balança não garante acentuação.
"""
from __future__ import annotations

import unicodedata

from .base import ScaleFormatter, register_formatter

PLU_WIDTH = 4
PRICE_WIDTH = 6
VALIDITY_WIDTH = 4
TEXT_WIDTH = 25
FIXED_MIDDLE = " " * 13 + "00000"


def _clean_text(text: str) -> str:
    """Maiúsculas, sem acento e sem os caracteres que quebram o arquivo
    ("#" é o separador de campo, TAB e quebra de linha separam registros)."""
    without_accents = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    for forbidden in ("#", "\t", "\r", "\n"):
        without_accents = without_accents.replace(forbidden, " ")
    return without_accents.upper().strip()


def _description(product: dict) -> str:
    """Descrição + unidade, sem repetir a unidade quando o nome já termina
    com ela (ex.: "Special Dog Carne Kg" com unidade "KG" fica só uma vez)."""
    description = _clean_text(product.get("description") or "")
    unit = _clean_text(product.get("unit") or "")
    if unit and not description.endswith(unit):
        description = f"{description} {unit}".strip()
    return description


def _build_record(plu: int, price_cents: int, validity_days: int, description: str) -> str:
    # Corte seco em 25 caracteres (no meio da palavra se precisar, igual ao
    # exemplo real: "ARRO" / "Z KG"). Espaço que sobrar na ponta do corte
    # sai, também igual ao exemplo ("MINI BITS " vira "MINI BITS").
    name = description[:TEXT_WIDTH].rstrip()
    text1 = description[:TEXT_WIDTH].rstrip()
    text2 = description[TEXT_WIDTH:TEXT_WIDTH * 2].strip()
    return (
        str(plu).zfill(PLU_WIDTH)
        + str(plu % 100).zfill(2)
        + str(plu).zfill(6)
        + str(price_cents).zfill(PRICE_WIDTH)
        + str(validity_days).zfill(VALIDITY_WIDTH)
        + FIXED_MIDDLE
        + f"{name}##{text1}##{text2}##"
        + "\t"
    )


def _build_terminator(plu: int) -> str:
    """Última linha do arquivo, no formato exato do exemplo real:
    "1890000000000000000000             00000######" + TAB."""
    return str(plu).zfill(PLU_WIDTH) + "0" * 18 + FIXED_MIDDLE + "######" + "\t"


class RamuzaAtenaFormatter(ScaleFormatter):
    brand = "ramuza_atena"
    verified = True  # layout conferido contra o arquivo real do cliente (ver topo)

    def build_table(self, products: list[dict]) -> bytes:
        lines = []
        highest_plu = 0

        for product in products:
            plu = int(str(product["plu"]).strip())
            if not 0 < plu < 10 ** PLU_WIDTH - 1:
                raise ValueError(f"PLU fora do limite de {PLU_WIDTH} dígitos da Ramuza: {product['plu']}")

            price_cents = round(float(product["price"]) * 100)
            if not 0 <= price_cents < 10 ** PRICE_WIDTH:
                raise ValueError(f"preço fora do limite de {PRICE_WIDTH} dígitos: {product}")

            validity_days = int(product.get("validity_days") or 0)
            if not 0 <= validity_days < 10 ** VALIDITY_WIDTH:
                raise ValueError(f"validade fora do limite de {VALIDITY_WIDTH} dígitos: {product}")

            lines.append(_build_record(plu, price_cents, validity_days, _description(product)))
            highest_plu = max(highest_plu, plu)

        lines.append(_build_terminator(highest_plu + 1))
        return ("\n".join(lines) + "\n").encode("utf-8-sig")


register_formatter(RamuzaAtenaFormatter())
