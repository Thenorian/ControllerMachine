"""
Balança Filizola. Baseado em `Exemplos Balança/TxitensFilizola.txt`.

>>> ATENÇÃO: NÃO VERIFICADO — esqueleto, não implementação. <<<
O padrão visível é "PLU (6 dígitos) + marcador 'P' + descrição + preço/validade
(10 dígitos)", com a descrição parecendo ocupar um campo de largura fixa que
corta caracteres do INÍCIO do texto quando ele não cabe (ex.: "SPECIAL CAT
CASTR. FRANGO" vira "CIAL CAT CASTR. FRANGO", perdendo o "SPE" inicial) — um
comportamento incomum, diferente do MGV5 (que corta do fim). Tentei fechar a
conta de largura total por linha e o número não bateu com o tamanho real
medido byte a byte do arquivo (39/42 bytes conforme a linha, contra os ~39
esperados pela minha contagem manual) — ou seja, tem pelo menos um campo que
não identifiquei ainda (provavelmente algo entre a descrição e o bloco de
preço/validade, ou um marcador de fim de linha que não é só CRLF).

Não vale a pena adivinhar esse último detalhe sem uma segunda fonte (manual
do fabricante ou teste com equipamento real) — programar uma balança de
verdade com um offset errado é pior do que não ter o formatter ainda. Ver
`Exemplos Balança/TxitensFilizola.txt` para os dados brutos.
"""
from __future__ import annotations

from .base import ScaleFormatter, register_formatter


class FilizolaFormatter(ScaleFormatter):
    brand = "filizola"
    verified = False

    def build_table(self, products: list[dict]) -> bytes:
        raise NotImplementedError(
            "Formatter da Filizola ainda não foi fechado com confiança — o campo de "
            "descrição (que corta pelo início quando o nome é longo) não teve a largura "
            "exata confirmada contra o tamanho real do arquivo de exemplo. Ver o "
            "comentário no topo deste arquivo antes de implementar."
        )


register_formatter(FilizolaFormatter())
