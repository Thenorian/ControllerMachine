"""
Cupom de abertura/fechamento de CAIXA (não é nota fiscal, não passa pela
SEFAZ nem pela Focus - é só o comprovante interno do movimento de caixa,
pedido do usuário: "quase um relatório do caixa"). Isolado do fluxo fiscal
de propósito - reaproveita só o builder ESC/POS genérico (devices/escpos.py),
nunca o layout/vocabulário de devices/printer_fiscal.py, pra não misturar
documento fiscal com documento interno.

Contrato de entrada do PAYLOAD (o que o Simple ERP manda, via
connector.send_fiscal_job com kind="print_fiscal_nfce" e
data["tipo_documento"]="caixa" - reaproveita o mesmo transporte, só muda o
tipo de documento e quem interpreta o payload, ver client/main.py):

    {
        "tipo_documento": "caixa",
        "operacao": "abertura" | "fechamento" | "parcial" | "resumo_dia",
        "emitente": {"razao_social", "cnpj" | "cpf"},
        "terminal_label": "opcional - nome do terminal/caixa",
        "operador": "opcional - nome de quem abriu/fechou",
        "opened_at": "dd/mm/aaaa hh:mm:ss",
        "opening_balance": 0.0,
        # "fechamento" e "parcial" ("parcial" = X report, sessão de caixa
        # ainda aberta, sem contagem/diferença):
        "closed_at": "dd/mm/aaaa hh:mm:ss",       # só "fechamento"
        "entradas": 0.0, "saidas": 0.0, "vendas": 0.0,
        "expected_balance": 0.0,                   # só "fechamento"
        "counted_balance": 0.0, "difference": 0.0, # só "fechamento"
        "payments_by_method": {"Dinheiro": 0.0, "Cartao de Credito": 0.0, ...},
        # "resumo_dia" - empresa sem abertura/fechamento formal de caixa
        # (require_cash_register desligada): resumo de TODAS as vendas de
        # hoje da empresa, sem sessão/terminal/saldo de caixa físico
        # nenhum - só sale_count/vendas/payments_by_method.
        "sale_count": 0,
    }
"""
from __future__ import annotations

from devices.escpos import EscPosBuilder, chars_per_line, format_brl

OPERACOES_VALIDAS = {"abertura", "fechamento", "parcial", "resumo_dia"}


def render_cupom_caixa(payload: dict, encoding: str = "cp860", paper_width_mm: int = 80,
                        mode: str = "escpos", cut_mode: str = "full") -> bytes:
    for campo in ("operacao", "emitente"):
        if campo not in payload:
            raise ValueError(f"payload de cupom de caixa incompleto - falta '{campo}'")
    if payload["operacao"] not in OPERACOES_VALIDAS:
        raise ValueError(f"payload de cupom de caixa invalido - 'operacao' deve ser um de {sorted(OPERACOES_VALIDAS)}")

    line_width = chars_per_line(paper_width_mm, fonte_pequena=False)
    left_col = line_width - 10
    value_col = 10

    b = EscPosBuilder(encoding=encoding, plain=(mode == "raw"))
    b.font(small=False)

    emitente = payload["emitente"]
    if emitente.get("razao_social"):
        b.align("center").bold(True).line(emitente["razao_social"]).bold(False)
    documento = f"CNPJ: {emitente['cnpj']}" if emitente.get("cnpj") else (
        f"CPF: {emitente['cpf']}" if emitente.get("cpf") else ""
    )
    if documento:
        b.line(documento)
    b.separator("=", line_width)
    titulo = {
        "abertura": "ABERTURA DE CAIXA",
        "fechamento": "FECHAMENTO DE CAIXA",
        "parcial": "RESUMO PARCIAL DE CAIXA",
        "resumo_dia": "RESUMO DE VENDAS DO DIA",
    }[payload["operacao"]]
    b.bold(True).line(titulo).bold(False)
    b.separator("-", line_width)

    b.align("left")
    if payload.get("terminal_label"):
        b.line(f"Caixa: {payload['terminal_label']}")
    if payload.get("operador"):
        b.line(f"Operador: {payload['operador']}")
    if payload.get("opened_at"):
        b.line(f"Abertura: {payload['opened_at']}")

    if payload["operacao"] == "abertura":
        b.separator("-", line_width)
        b.line(f"{'Valor de abertura R$':<{left_col}}{format_brl(payload.get('opening_balance', 0)):>{value_col}}")

    elif payload["operacao"] == "resumo_dia":
        # Sem sessão de caixa nenhuma pra amarrar (empresa não usa
        # abertura/fechamento formal) - só o total vendido hoje, sem
        # nenhuma linha de saldo/conferência de caixa físico.
        b.separator("-", line_width)
        b.line(f"{'Vendas realizadas':<{left_col}}{payload.get('sale_count', 0):>{value_col}}")
        b.line(f"{'Total vendido R$':<{left_col}}{format_brl(payload.get('vendas', 0)):>{value_col}}")

        payments = payload.get("payments_by_method") or {}
        if payments:
            b.separator("-", line_width)
            b.line("Vendas por forma de pagamento:")
            for forma, valor in payments.items():
                b.line(f"{forma:<{left_col}}{format_brl(valor):>{value_col}}")

    else:
        # "fechamento" e "parcial" - mesmo corpo (saldo de caixa físico +
        # vendas por forma de pagamento); só "fechamento" acrescenta a
        # conferência (valor contado/diferença), porque "parcial" é um X
        # report com o caixa ainda aberto, sem ninguém ter contado nada.
        if payload.get("closed_at"):
            b.line(f"Fechamento: {payload['closed_at']}")
        b.separator("-", line_width)
        b.line(f"{'Valor de abertura R$':<{left_col}}{format_brl(payload.get('opening_balance', 0)):>{value_col}}")
        b.line(f"{'Entradas R$':<{left_col}}{format_brl(payload.get('entradas', 0)):>{value_col}}")
        b.line(f"{'Saidas R$':<{left_col}}{format_brl(payload.get('saidas', 0)):>{value_col}}")
        b.line(f"{'Vendas R$':<{left_col}}{format_brl(payload.get('vendas', 0)):>{value_col}}")

        payments = payload.get("payments_by_method") or {}
        if payments:
            b.separator("-", line_width)
            b.line("Vendas por forma de pagamento:")
            for forma, valor in payments.items():
                b.line(f"{forma:<{left_col}}{format_brl(valor):>{value_col}}")

        b.separator("-", line_width)
        b.bold(True).line(f"{'Valor esperado R$':<{left_col}}{format_brl(payload.get('expected_balance', 0)):>{value_col}}").bold(False)
        if payload["operacao"] == "fechamento":
            b.line(f"{'Valor contado R$':<{left_col}}{format_brl(payload.get('counted_balance', 0)):>{value_col}}")
            diferenca = payload.get('difference', 0)
            b.bold(True).line(f"{'Diferenca R$':<{left_col}}{format_brl(diferenca):>{value_col}}").bold(False)

    b.separator("=", line_width)
    b.align("center").line("Comprovante interno - sem valor fiscal")

    b.feed(3).cut(cut_mode)
    return b.build()
