"""
Motor de template mínimo pros campos de texto livre do modelo de impressão
(cabeçalho, rodapé, mensagem da empresa) — suporta:

  {{campo}}        -> substitui pelo valor do campo (lista de campos
                       disponíveis em devices/printer_fiscal.py::_contexto_template)
                       — campo desconhecido ou vazio vira "" (nunca quebra a
                       impressão por um nome errado/typo no template).
  {"x"*8} {'x'*8}  -> repete o caractere/trecho "x" 8 vezes (mesmo efeito de
                       uma linha de traços, ex.: {"-"*20}). De propósito NÃO
                       é eval() de Python de verdade — só entende essa forma
                       exata (string literal * inteiro) via regex, pra nunca
                       rodar código arbitrário a partir de um template salvo
                       em config.json (segurança: local ou não, nada externo
                       vira código executado neste projeto).

Cada linha final é sempre cortada em `largura` caracteres — não importa o
que o template peça, a saída nunca ultrapassa a bobina.
"""
from __future__ import annotations

import re

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_REPEAT_RE = re.compile(r"\{\s*(['\"])(.*?)\1\s*\*\s*(\d+)\s*\}")

# Teto de segurança pro N em {"x"*N} — só pra não montar uma string enorme
# em memória por um typo (ex.: {"x"*99999999}); o corte por `largura` no
# final já resolveria visualmente, mas isso evita a alocação gigante antes.
_MAX_REPETICOES = 500


def _substituir_campos(linha: str, contexto: dict) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: str(contexto.get(m.group(1), "") or ""), linha)


def _substituir_repeticoes(linha: str) -> str:
    def _sub(m: re.Match) -> str:
        trecho, n = m.group(2), int(m.group(3))
        return trecho * min(n, _MAX_REPETICOES)
    return _REPEAT_RE.sub(_sub, linha)


def renderizar(texto: str, contexto: dict, largura: int) -> list[str]:
    """Processa um bloco de texto livre (várias linhas) e devolve a lista de
    linhas já prontas pra imprimir — placeholders substituídos, repetições
    expandidas e cada linha cortada em `largura` caracteres."""
    if not texto:
        return []
    linhas = []
    for linha in texto.splitlines():
        linha = _substituir_campos(linha, contexto)
        linha = _substituir_repeticoes(linha)
        linhas.append(linha[:largura])
    return linhas
