"""
Balança Toledo Prix / linha MGV5.

Layout confirmado por medição direta dos bytes dos arquivos de exemplo
(`Exemplos Balança/TxitensMGV5(UTF-8).txt` e a variante IBM860) — não é
suposição: as 146 linhas de dados desses arquivos têm exatamente 320 bytes
cada (conferido com leitura binária, não pela visualização de editor de
texto). Estrutura de cada registro:

    offset  tamanho  campo
    0       3        prefixo fixo (espaços)
    3       8        PLU, zero-padded (ex.: "00000002")
    11      6        preço em centavos, zero-padded (ex.: "001390" = R$ 13,90)
    17      3        validade em dias (ex.: "365")
    20      25        "zona 1" da descrição
    45      25        "zona 2" da descrição (continuação, se necessário)
    70      250      preenchido com espaços até completar 320 bytes

A descrição + unidade (ex.: "SPECIAL GOLD FILHO.KG KG") é tratada como um
texto único de até 50 caracteres, dividido em duas zonas de 25:
  - se o texto cabe em 25 chars: fica todo na zona 1, alinhado à direita
    (padding à esquerda) — confirmado comparando várias linhas de exemplo
    com nomes curtos.
  - se passa de 25: zona 1 recebe os primeiros 25 caracteres (corta no meio
    da palavra se precisar, sem tentar quebrar por palavra inteira — é
    exatamente o que os exemplos mostram, ex. "ARROZ" cortado em "ARRO"/"Z"),
    zona 2 recebe o restante, também alinhado à direita dentro dos 25.

O que NÃO foi confirmado com certeza: o significado dos 250 bytes finais
(claramente reservado/não usado nos exemplos — todos aparecem em branco) e a
convenção exata do registro terminador (nos exemplos, a última linha tem
PLU 1890 com preço e validade zerados e descrição em branco — não dá pra
saber com certeza se "1890" é um valor mágico fixo do protocolo ou só o
próximo PLU livre daquele cadastro específico). Por segurança, o terminador
aqui é parametrizável e, por padrão, usa PLU "00000000" com tudo zerado —
ajustar `terminator_plu` se o equipamento real exigir outro valor.
"""
from __future__ import annotations

from .base import ScaleFormatter, register_formatter

RECORD_LENGTH = 320
PREFIX = "   "
PLU_WIDTH = 8
PRICE_WIDTH = 6
VALIDITY_WIDTH = 3
DESC_ZONE_WIDTH = 25


def _build_record(plu: str, price_cents: int, validity_days: int, name_field: str) -> str:
    combined = name_field[:DESC_ZONE_WIDTH * 2]  # nunca deixa passar de 50 chars
    if len(combined) <= DESC_ZONE_WIDTH:
        zone1 = combined.rjust(DESC_ZONE_WIDTH)
        zone2 = " " * DESC_ZONE_WIDTH
    else:
        zone1 = combined[:DESC_ZONE_WIDTH]
        zone2 = combined[DESC_ZONE_WIDTH:].rjust(DESC_ZONE_WIDTH)

    record = (
        PREFIX
        + plu.zfill(PLU_WIDTH)
        + str(price_cents).zfill(PRICE_WIDTH)
        + str(validity_days).zfill(VALIDITY_WIDTH)
        + zone1
        + zone2
    )
    return record.ljust(RECORD_LENGTH)


class ToledoMGV5Formatter(ScaleFormatter):
    """Existe em duas variantes (mesmo layout de campos, encoding de texto
    diferente) porque os dois arquivos de exemplo mostram equipamentos MGV5
    com firmwares/modelos que esperam charset diferente: `toledo_mgv5_utf8`
    e `toledo_mgv5_ibm860`. Para os nomes de produto deste dataset (sem
    acento) os bytes resultantes são idênticos nas duas — a diferença só
    aparece de verdade com descrição acentuada (ex.: "AÇÚCAR")."""

    verified = True  # layout conferido por medição de bytes contra os exemplos

    def __init__(self, brand: str, encoding: str, terminator_plu: str = "00000000"):
        self.brand = brand
        self.encoding = encoding
        self.terminator_plu = terminator_plu

    def build_table(self, products: list[dict]) -> bytes:
        lines = []
        for product in products:
            price_cents = round(product["price"] * 100)
            if price_cents > 10 ** PRICE_WIDTH - 1:
                raise ValueError(f"preço grande demais para o campo de {PRICE_WIDTH} dígitos: {product}")

            name_field = f"{product['description']} {product.get('unit', '')}".strip()
            lines.append(_build_record(
                plu=str(product["plu"]),
                price_cents=price_cents,
                validity_days=product.get("validity_days", 365),
                name_field=name_field,
            ))

        lines.append(_build_record(self.terminator_plu, 0, 0, ""))

        text = "\r\n".join(lines) + "\r\n"
        return text.encode(self.encoding, errors="replace")


register_formatter(ToledoMGV5Formatter(brand="toledo_mgv5_utf8", encoding="utf-8"))
register_formatter(ToledoMGV5Formatter(brand="toledo_mgv5_ibm860", encoding="cp860"))
