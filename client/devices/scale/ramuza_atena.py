"""
Balança Ramuza (linha Atena) — formato de largura VARIÁVEL, delimitado por
"##", diferente do Toledo MGV5 (que é registro fixo). Baseado em
`Exemplos Balança/TxitensrRAMUZA(ATENA 1 UTF-8).txt`.

>>> ATENÇÃO: NÃO VERIFICADO BYTE A BYTE. <<<
Diferente do formatter do MGV5, aqui a contagem exata de dígitos do prefixo
numérico (PLU / preço / validade) não foi confirmada com certeza — o exemplo
tem um bloco de 22 dígitos antes da descrição e não ficou claro qual a
divisão exata entre PLU e os demais campos sem uma segunda fonte pra
comparar. O padrão de delimitador (texto cortado em pedaços de até ~25
caracteres, unidos por "##", terminado em "####") está mais claro e foi
mantido. Revisar contra a documentação do fabricante ou testar com o
equipamento real antes de confiar em produção — por enquanto isso é só um
esqueleto funcional, não uma implementação pronta.

Estrutura observada por linha de exemplo:
    "0002390000390013900365             00000SPECIAL GOLD FILHO.KG##SPECIAL GOLD FILHO.KG####"
     |--- 22 dígitos --------------------||-5-||--- descrição (segmentada por ##) ---|
"""
from __future__ import annotations

from .base import ScaleFormatter, register_formatter

SEGMENT_WIDTH = 26


class RamuzaAtenaFormatter(ScaleFormatter):
    brand = "ramuza_atena"
    verified = False

    def build_table(self, products: list[dict]) -> bytes:
        raise NotImplementedError(
            "Formatter da Ramuza/Atena é só um esqueleto — o mapeamento exato dos "
            "22 dígitos do prefixo (quantos são PLU, quantos são preço, quantos são "
            "validade) não foi confirmado contra o equipamento real. Ver o comentário "
            "no topo deste arquivo e o exemplo em Exemplos Balança/ antes de implementar "
            "de verdade. `_split_into_segments` abaixo já cobre a parte do texto que "
            "ESTÁ confirmada (segmentação por '##', terminador '####')."
        )

    @staticmethod
    def _split_into_segments(text: str) -> str:
        """Parte confirmada do formato: o texto (descrição, e unidade quando
        não cabe junto) é cortado em blocos de até `SEGMENT_WIDTH` caracteres,
        cada um seguido por '##', com '####' marcando o fim."""
        segments = [text[i:i + SEGMENT_WIDTH] for i in range(0, len(text), SEGMENT_WIDTH)] or [""]
        return "##".join(segments) + "####"


register_formatter(RamuzaAtenaFormatter())
