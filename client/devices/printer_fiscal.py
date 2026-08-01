"""
Renderização do DANFE-NFCe (o cupom impresso depois que a nota já foi
autorizada pela SEFAZ). Este módulo NÃO emite nem assina nota — isso é
responsabilidade do Simple ERP (ou de um provedor tipo Focus NFe). Aqui só
entra o JSON já autorizado e sai um cupom ESC/POS pronto pra imprimir em
qualquer impressora térmica comum — NFC-e não exige impressora fiscal
homologada (ECF), diferente do modelo antigo.

IMPORTANTE — leiaute de referência, não é certificação: o layout abaixo segue
a estrutura geral pedida pelo Manual de Orientação do Contribuinte da NFC-e
(chave de acesso, protocolo, QR Code, itens, totais), mas os detalhes visuais
exatos (o que é obrigatório aparecer, tamanho de fonte, posição do QR Code
etc.) mudam com frequência por atualização da SEFAZ. Revisar contra o MOC
vigente antes de usar em produção — é por isso que isso está isolado neste
único arquivo (ver o handoff no Obsidian, seção "Impressão fiscal").

Contrato de entrada (o que o Simple ERP manda, via connector.send_fiscal_job):

    {
        "chave_acesso": "44 dígitos",
        "protocolo_autorizacao": "...",
        "data_hora_autorizacao": "...",
        "ambiente": "producao" | "homologacao",
        "emitente": {"cnpj", "razao_social", "ie", "endereco"},
        "consumidor": {"cpf_cnpj": "opcional"},
        "itens": [{"codigo", "descricao", "unidade", "quantidade", "valor_unitario", "valor_total"}],
        "totais": {"valor_produtos", "valor_descontos", "valor_total"},
        "pagamentos": [{"forma", "valor"}],
        "troco": 0,
        "qrcode_url": "...",
        "mensagem_adicional": "opcional",
    }
"""
from __future__ import annotations

from devices.escpos import EscPosBuilder, chars_per_line


def render_danfe_nfce(payload: dict, encoding: str = "cp860", paper_width_mm: int = 80,
                       mode: str = "escpos") -> bytes:
    LINE_WIDTH = chars_per_line(paper_width_mm)
    VALUE_COL = 10  # cabe "-9999999.99" folgado, mesma coluna nos dois tamanhos de bobina
    LEFT_COL = LINE_WIDTH - VALUE_COL
    b = EscPosBuilder(encoding=encoding, plain=(mode == "raw"))

    emitente = payload["emitente"]
    b.align("center").bold(True).line(emitente.get("razao_social", "")).bold(False)
    b.line(f"CNPJ: {emitente.get('cnpj', '')}  IE: {emitente.get('ie', '')}")
    b.line(emitente.get("endereco", ""))
    b.separator("=", LINE_WIDTH)
    b.line("DANFE NFC-e - Documento Auxiliar da")
    b.line("Nota Fiscal de Consumidor Eletrônica")
    if payload.get("ambiente") == "homologacao":
        b.bold(True).line("*** AMBIENTE DE HOMOLOGACAO ***").bold(False)
    b.separator("-", LINE_WIDTH)

    b.align("left")
    for item in payload.get("itens", []):
        descricao = item["descricao"][:LINE_WIDTH]
        b.line(descricao)
        qtd = item["quantidade"]
        unit = item["unidade"]
        v_unit = item["valor_unitario"]
        v_total = item["valor_total"]
        b.line(f"{qtd} {unit} x {v_unit:.2f}".ljust(LEFT_COL) + f"{v_total:>{VALUE_COL}.2f}")

    b.separator("-", LINE_WIDTH)
    totais = payload["totais"]
    b.line(f"{'Total de itens':<{LEFT_COL}}{len(payload.get('itens', [])):>{VALUE_COL}}")
    b.line(f"{'Valor dos produtos':<{LEFT_COL}}{totais['valor_produtos']:>{VALUE_COL}.2f}")
    if totais.get("valor_descontos"):
        b.line(f"{'Descontos':<{LEFT_COL}}{-totais['valor_descontos']:>{VALUE_COL}.2f}")
    b.bold(True).line(f"{'VALOR A PAGAR':<{LEFT_COL}}{totais['valor_total']:>{VALUE_COL}.2f}").bold(False)

    b.separator("-", LINE_WIDTH)
    for pagamento in payload.get("pagamentos", []):
        b.line(f"{pagamento['forma']:<{LEFT_COL}}{pagamento['valor']:>{VALUE_COL}.2f}")
    if payload.get("troco"):
        b.line(f"{'Troco':<{LEFT_COL}}{payload['troco']:>{VALUE_COL}.2f}")

    consumidor = payload.get("consumidor") or {}
    if consumidor.get("cpf_cnpj"):
        b.separator("-", LINE_WIDTH)
        b.line(f"CPF/CNPJ do consumidor: {consumidor['cpf_cnpj']}")

    b.separator("=", LINE_WIDTH)
    b.align("center")
    b.line(f"Chave de acesso:")
    b.line(_format_chave_acesso(payload["chave_acesso"]))
    b.line(f"Protocolo de autorização: {payload['protocolo_autorizacao']}")
    b.line(payload.get("data_hora_autorizacao", ""))

    if payload.get("qrcode_url"):
        # Nota: comando de QR Code varia por fabricante (Epson, Bematech,
        # Elgin etc. têm variações do GS('k' ESC/POS 2D). Deixado como texto
        # por enquanto — trocar pelo comando de QR Code real da impressora
        # alvo quando um modelo específico for definido.
        b.line("[QR Code]")
        b.line(payload["qrcode_url"][:LINE_WIDTH])

    if payload.get("mensagem_adicional"):
        b.separator("-", LINE_WIDTH)
        b.align("left").line(payload["mensagem_adicional"])

    b.feed(3).cut()
    return b.build()


def _format_chave_acesso(chave: str) -> str:
    return " ".join(chave[i:i + 4] for i in range(0, len(chave), 4))
