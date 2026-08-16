"""
Renderização do DANFE-NFCe e do Cupom não fiscal (o comprovante impresso
depois que a venda foi concluída — DANFE só depois que a nota já foi
autorizada pela SEFAZ). Este módulo NÃO emite nem assina nota — isso é
responsabilidade do Simple ERP (ou de um provedor tipo Focus NFe). Aqui só
entra o JSON já autorizado (ou, no caso de cupom, só os dados da venda) e sai
um documento ESC/POS pronto pra imprimir em qualquer impressora térmica
comum — NFC-e não exige impressora fiscal homologada (ECF), diferente do
modelo antigo.

Leiaute segue a especificação em Recursos/Documentação/Interna/Simple ERP/
NFCe.md (Obsidian) — Divisões I a IX do Manual de Especificações Técnicas do
DANFE NFC-e e QR Code. Revisar contra o Manual vigente antes de usar em
produção — é por isso que isso está isolado neste único arquivo (ver o
handoff no Obsidian, seção "Impressão fiscal").

Contrato de entrada (o que o Simple ERP manda, via connector.send_fiscal_job):

    {
        "tipo_documento": "nfce" | "cupom",  # opcional, default "nfce" —
            "cupom" nunca imprime QR Code nem nenhum dado fiscal (chave de
            acesso, protocolo, número, série) — só o resumo da venda.
        "chave_acesso": "44 dígitos",             # obrigatório se nfce
        "protocolo_autorizacao": "...",            # obrigatório se nfce (exceto contingência)
        "data_hora_autorizacao": "...",
        "ambiente": "producao" | "homologacao",
        "contingencia": False,          # opcional — nfce emitida offline
        "via": 1,                       # opcional — 2 = "Via do Estabelecimento"
        "numero": "...", "serie": "...", "data_emissao": "...",  # Divisão VII
        "url_consulta_chave": "...",    # opcional — Divisão IV
        "qrcode_url": "...",            # obrigatório se nfce — já vem pronta do provedor fiscal
        "emitente": {"cnpj", "cpf", "razao_social", "ie", "endereco"},
        "consumidor": {"cpf_cnpj": "opcional"},
        "atendente": "opcional — nome de quem atendeu",
        "pdv_label": "opcional — identificação do caixa/PDV (ex.: 'PDV 1')",
        "itens": [{"codigo", "descricao", "unidade", "quantidade", "valor_unitario", "valor_total"}],
        "totais": {"valor_produtos", "valor_descontos", "valor_total", "valor_frete", "valor_seguro", "valor_outras_despesas"},
        "pagamentos": [{"forma", "valor"}],
        "troco": 0,
        "mensagem_fisco": "opcional — infAdFisco/xMsg (Divisão VIII)",
        "mensagem_empresa": "opcional — infCpl / recado do lojista (Divisão IX), nada impresso se ausente",
    }
"""
from __future__ import annotations

from devices.escpos import EscPosBuilder, chars_per_line, format_brl

TEXTO_HOMOLOGACAO = "EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
TEXTO_CONTINGENCIA = ("EMITIDA EM CONTINGENCIA", "Pendente de autorizacao")


def render_danfe_nfce(payload: dict, encoding: str = "cp860", paper_width_mm: int = 80,
                       mode: str = "escpos", cut_mode: str = "full",
                       header_text: str = "", footer_text: str = "") -> bytes:
    for campo in ("emitente", "itens", "totais"):
        if campo not in payload:
            raise ValueError(f"payload de impressão fiscal incompleto — falta '{campo}'")

    tipo_documento = payload.get("tipo_documento", "nfce")
    is_cupom = tipo_documento == "cupom"
    if not is_cupom and not payload.get("chave_acesso"):
        raise ValueError("payload de impressão fiscal incompleto — falta 'chave_acesso' (tipo_documento=nfce)")

    LINE_WIDTH = chars_per_line(paper_width_mm)
    VALUE_COL = 10  # cabe "-9999999.99" folgado, mesma coluna nos dois tamanhos de bobina
    LEFT_COL = LINE_WIDTH - VALUE_COL
    b = EscPosBuilder(encoding=encoding, plain=(mode == "raw"))
    contingencia = bool(payload.get("contingencia"))

    if header_text:
        b.align("center")
        for line in header_text.splitlines():
            b.line(line)
        b.separator("-", LINE_WIDTH)

    # ---- Divisão I — Cabeçalho ----
    emitente = payload["emitente"]
    b.align("center").bold(True).line(emitente.get("razao_social", "")).bold(False)
    documento = f"CNPJ: {emitente['cnpj']}" if emitente.get("cnpj") else f"CPF: {emitente.get('cpf', '')}"
    if emitente.get("ie"):
        documento += f"  IE: {emitente['ie']}"
    b.line(documento)
    b.line(emitente.get("endereco", ""))
    if contingencia:
        _linhas_contingencia(b, LINE_WIDTH)
    b.separator("=", LINE_WIDTH)
    if is_cupom:
        b.line("CUPOM - SEM VALOR FISCAL")
    else:
        b.line("DANFE NFC-e - Documento Auxiliar da")
        b.line("Nota Fiscal de Consumidor Eletronica")
    if payload.get("ambiente") == "homologacao":
        b.bold(True).line(TEXTO_HOMOLOGACAO).bold(False)
    b.separator("-", LINE_WIDTH)

    # ---- Atendimento (exigido em todos os documentos, cupom ou nota) ----
    if payload.get("atendente") or payload.get("pdv_label"):
        b.align("left")
        if payload.get("atendente"):
            b.line(f"Atendente: {payload['atendente']}")
        if payload.get("pdv_label"):
            b.line(f"Caixa: {payload['pdv_label']}")
        b.separator("-", LINE_WIDTH)

    # ---- Divisão II — Itens ----
    b.align("left")
    for item in payload.get("itens", []):
        codigo = item.get("codigo", "")
        descricao = f"{codigo} {item['descricao']}".strip()
        for linha in _quebrar_por_palavra(descricao, LINE_WIDTH):
            b.line(linha)
        qtd = item["quantidade"]
        unit = item["unidade"]
        v_unit = format_brl(item["valor_unitario"])
        v_total = item["valor_total"]
        b.line(f"{qtd} {unit} x {v_unit}".ljust(LEFT_COL) + f"{format_brl(v_total):>{VALUE_COL}}")

    # ---- Divisão III — Totais ----
    b.separator("-", LINE_WIDTH)
    totais = payload["totais"]
    b.line(f"{'Qtde. total de itens':<{LEFT_COL}}{len(payload.get('itens', [])):>{VALUE_COL}}")
    b.line(f"{'Valor total R$':<{LEFT_COL}}{format_brl(totais['valor_produtos']):>{VALUE_COL}}")
    acrescimos = (totais.get("valor_frete") or 0) + (totais.get("valor_seguro") or 0) + (totais.get("valor_outras_despesas") or 0)
    if acrescimos:
        b.line(f"{'Acrescimos R$':<{LEFT_COL}}{format_brl(acrescimos):>{VALUE_COL}}")
    if totais.get("valor_descontos"):
        b.line(f"{'Desconto R$':<{LEFT_COL}}{format_brl(-totais['valor_descontos']):>{VALUE_COL}}")
    b.bold(True).line(f"{'VALOR A PAGAR R$':<{LEFT_COL}}{format_brl(totais['valor_total']):>{VALUE_COL}}").bold(False)

    # ---- Divisão III — Pagamentos ----
    if payload.get("pagamentos"):
        b.separator("-", LINE_WIDTH)
        for pagamento in payload["pagamentos"]:
            b.line(f"{pagamento['forma']:<{LEFT_COL}}{format_brl(pagamento['valor']):>{VALUE_COL}}")
        if payload.get("troco"):
            b.line(f"{'Troco':<{LEFT_COL}}{format_brl(payload['troco']):>{VALUE_COL}}")

    # ---- Divisão VI — Consumidor (sempre presente) ----
    b.separator("-", LINE_WIDTH)
    b.line(_linha_consumidor(payload.get("consumidor") or {}))

    if not is_cupom:
        # ---- Divisão IV — Consulta por chave de acesso ----
        b.separator("=", LINE_WIDTH)
        b.align("center")
        if payload.get("url_consulta_chave"):
            b.line("Consulte pela Chave de Acesso em")
            b.line(payload["url_consulta_chave"][:LINE_WIDTH])
        b.line("Chave de acesso:")
        b.line(_format_chave_acesso(payload["chave_acesso"]))

        # ---- Divisão VII — Identificação da NFC-e / protocolo ----
        if payload.get("numero"):
            b.line(f"NFC-e no {payload['numero']}  Serie {payload.get('serie', '')}")
        if payload.get("data_emissao"):
            b.line(payload["data_emissao"])
        if contingencia:
            _linhas_contingencia(b, LINE_WIDTH)
        else:
            if payload.get("protocolo_autorizacao"):
                b.line(f"Protocolo de autorizacao: {payload['protocolo_autorizacao']}")
            if payload.get("data_hora_autorizacao"):
                b.line(payload["data_hora_autorizacao"])
        if payload.get("via") == 2:
            b.bold(True).line("Via do Estabelecimento").bold(False)

        # ---- Divisão V — QR Code ----
        if payload.get("qrcode_url"):
            b.feed(1)
            b.qr_code(payload["qrcode_url"])

    # ---- Divisão VIII — Mensagem fiscal ----
    mensagem_fisco = payload.get("mensagem_fisco")
    if mensagem_fisco:
        b.separator("-", LINE_WIDTH)
        b.align("left").line(mensagem_fisco)

    # ---- Divisão IX — Mensagem do contribuinte (nada se não houver) ----
    mensagem_empresa = payload.get("mensagem_empresa") or payload.get("mensagem_adicional")
    if mensagem_empresa:
        b.separator("-", LINE_WIDTH)
        b.align("left").line(mensagem_empresa)

    if footer_text:
        b.separator("-", LINE_WIDTH)
        b.align("center")
        for line in footer_text.splitlines():
            b.line(line)

    b.feed(3).cut(cut_mode)
    return b.build()


def _linha_consumidor(consumidor: dict) -> str:
    documento = consumidor.get("cpf_cnpj")
    if not documento:
        return "CONSUMIDOR NAO IDENTIFICADO"
    digitos = "".join(ch for ch in documento if ch.isdigit())
    rotulo = "CPF" if len(digitos) <= 11 else "CNPJ"
    return f"CONSUMIDOR {rotulo}: {documento}"


def _linhas_contingencia(b: EscPosBuilder, line_width: int) -> None:
    b.bold(True)
    for linha in TEXTO_CONTINGENCIA:
        b.line(linha)
    b.bold(False)


def _quebrar_por_palavra(texto: str, largura: int) -> list[str]:
    """Quebra por palavra (nunca corta uma palavra ao meio) — palavra maior
    que a própria largura da bobina é o único caso em que corta, pra não
    entrar em loop infinito sem nunca conseguir encaixar."""
    linhas: list[str] = []
    linha_atual = ""
    for palavra in texto.split():
        candidata = f"{linha_atual} {palavra}".strip()
        if len(candidata) <= largura:
            linha_atual = candidata
            continue
        if linha_atual:
            linhas.append(linha_atual)
        if len(palavra) > largura:
            while len(palavra) > largura:
                linhas.append(palavra[:largura])
                palavra = palavra[largura:]
        linha_atual = palavra
    if linha_atual:
        linhas.append(linha_atual)
    return linhas or [""]


def _format_chave_acesso(chave: str) -> str:
    return " ".join(chave[i:i + 4] for i in range(0, len(chave), 4))
