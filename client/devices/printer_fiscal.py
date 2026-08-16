"""
Renderização do DANFE-NFCe e do Cupom não fiscal (o comprovante impresso
depois que a venda foi concluída — DANFE só depois que a nota já foi
autorizada pela SEFAZ). Este módulo NÃO emite nem assina nota — isso é
responsabilidade do Simple ERP (ou de um provedor tipo Focus NFe). O Simple
ERP só manda DADOS da venda (payload abaixo) — quem decide COMO o documento
aparece (cabeçalho extra, mensagem padrão, tamanho do QR, e no cupom até a
ordem/composição do documento) é sempre o `template`, configurado localmente
aqui no Controller Machine (ver gui/template_editor.py) e nunca pelo Simple
ERP — layout é responsabilidade exclusiva deste projeto.

Leiaute padrão segue a especificação em Recursos/Documentação/Interna/
Simple ERP/NFCe.md (Obsidian) — Divisões I a IX do Manual de Especificações
Técnicas do DANFE NFC-e e QR Code. Revisar contra o Manual vigente antes de
usar em produção — é por isso que isso está isolado neste único arquivo (ver
o handoff no Obsidian, seção "Impressão fiscal").

Contrato de entrada do PAYLOAD (o que o Simple ERP manda, via
connector.send_fiscal_job — nunca contém nada de layout):

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
        "mensagem_empresa": "opcional — infCpl / recado do lojista (Divisão IX) desta venda específica",
    }

Contrato do TEMPLATE (configurado localmente, ver DEFAULT_TEMPLATE abaixo) —
mora em device["settings"]["template"] no config.json, nunca no payload.
"""
from __future__ import annotations

from devices.escpos import EscPosBuilder, chars_per_line, format_brl

TEXTO_HOMOLOGACAO = "EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
TEXTO_CONTINGENCIA = ("EMITIDA EM CONTINGENCIA", "Pendente de autorizacao")

# Modo Básico do editor de modelo mexe só nestas chaves. Qualquer uma que
# faltar usa o valor abaixo — dispositivo configurado antes do editor
# existir continua imprimindo exatamente igual.
DEFAULT_TEMPLATE = {
    "header_text": "",
    "footer_text": "",
    "mostrar_ie": True,
    "mensagem_empresa": "",       # fallback fixo se a venda não trouxer mensagem_empresa própria
    "qr_module_size": 6,
    "qr_error_correction": "M",
    "cupom_titulo": "CUPOM - SEM VALOR FISCAL",
    # Modo Avançado (só cupom — ver módulo README/aviso na GUI). Lista de
    # blocos que SUBSTITUI o documento padrão inteiro quando presente.
    # IMPORTANTE: nota fiscal (tipo_documento="nfce") NUNCA lê esta chave —
    # a trava não é validação, é estrutural (ver render_danfe_nfce abaixo),
    # não tem como um template mal configurado tirar QR/chave/protocolo/
    # consumidor de uma NFC-e, mesmo editando o config.json na mão.
    "blocos_customizados": None,
}

# Vocabulário de blocos do editor avançado — de propósito NÃO existe bloco
# de QR Code, chave de acesso, protocolo, número ou série: essas peças são
# exclusivas do fluxo fiscal fixo, nem aparecem como opção pra montar um
# cupom customizado.
_TIPOS_BLOCO_VALIDOS = {
    "cabecalho", "atendente", "itens", "totais", "pagamentos", "consumidor",
    "mensagem_empresa", "mensagem_fisco", "texto", "separador", "espaco",
}


def render_danfe_nfce(payload: dict, encoding: str = "cp860", paper_width_mm: int = 80,
                       mode: str = "escpos", cut_mode: str = "full",
                       template: dict | None = None) -> bytes:
    for campo in ("emitente", "itens", "totais"):
        if campo not in payload:
            raise ValueError(f"payload de impressão fiscal incompleto — falta '{campo}'")

    tipo_documento = payload.get("tipo_documento", "nfce")
    is_cupom = tipo_documento == "cupom"
    if not is_cupom and not payload.get("chave_acesso"):
        raise ValueError("payload de impressão fiscal incompleto — falta 'chave_acesso' (tipo_documento=nfce)")

    tpl = {**DEFAULT_TEMPLATE, **(template or {})}
    dims = _Dimensoes(paper_width_mm)
    b = EscPosBuilder(encoding=encoding, plain=(mode == "raw"))
    contingencia = bool(payload.get("contingencia"))

    blocos = tpl.get("blocos_customizados") if is_cupom else None
    if blocos:
        for bloco in blocos:
            _renderizar_bloco(b, bloco, payload, tpl, dims, is_cupom, contingencia)
    else:
        _renderizar_documento_padrao(b, payload, tpl, is_cupom, contingencia, dims)

    b.feed(3).cut(cut_mode)
    return b.build()


class _Dimensoes:
    """Larguras de coluna derivadas da bobina — agrupadas pra não passar 3
    parâmetros soltos pra cada função de renderização."""

    def __init__(self, paper_width_mm: int):
        self.line_width = chars_per_line(paper_width_mm)
        self.value_col = 10  # cabe "-9999999.99" folgado, mesma coluna nos dois tamanhos de bobina
        self.left_col = self.line_width - self.value_col


def _renderizar_documento_padrao(b: EscPosBuilder, payload: dict, tpl: dict, is_cupom: bool,
                                  contingencia: bool, dims: "_Dimensoes") -> None:
    """Fluxo fixo — usado sempre pra nota fiscal, e pro cupom quando o Modo
    Avançado não tiver definido blocos_customizados (Modo Básico)."""
    if tpl["header_text"]:
        b.align("center")
        for line in tpl["header_text"].splitlines():
            b.line(line)
        b.separator("-", dims.line_width)

    _renderizar_cabecalho(b, payload, tpl, is_cupom, contingencia, dims.line_width)
    _renderizar_atendente(b, payload, dims.line_width)
    _renderizar_itens(b, payload, dims)
    _renderizar_totais(b, payload, dims)
    _renderizar_pagamentos(b, payload, dims)

    b.separator("-", dims.line_width)
    b.align("left").line(_linha_consumidor(payload.get("consumidor") or {}))

    if not is_cupom:
        _renderizar_divisao_fiscal(b, payload, dims, contingencia, tpl)

    _renderizar_mensagem_fisco(b, payload, dims.line_width)
    _renderizar_mensagem_empresa(b, payload, tpl, dims.line_width)

    if tpl["footer_text"]:
        b.separator("-", dims.line_width)
        b.align("center")
        for line in tpl["footer_text"].splitlines():
            b.line(line)


def _renderizar_bloco(b: EscPosBuilder, bloco: dict, payload: dict, tpl: dict,
                       dims: "_Dimensoes", is_cupom: bool, contingencia: bool) -> None:
    """Modo Avançado (só cupom) — cada bloco da lista `blocos_customizados`
    vira uma chamada aqui. Tipo desconhecido/inválido é ignorado (nunca
    derruba a impressão inteira por um bloco malformado)."""
    tipo = bloco.get("tipo")
    if tipo not in _TIPOS_BLOCO_VALIDOS:
        return

    if tipo == "cabecalho":
        _renderizar_cabecalho(b, payload, tpl, is_cupom, contingencia, dims.line_width)
    elif tipo == "atendente":
        _renderizar_atendente(b, payload, dims.line_width)
    elif tipo == "itens":
        _renderizar_itens(b, payload, dims)
    elif tipo == "totais":
        _renderizar_totais(b, payload, dims)
    elif tipo == "pagamentos":
        _renderizar_pagamentos(b, payload, dims)
    elif tipo == "consumidor":
        b.align("left").line(_linha_consumidor(payload.get("consumidor") or {}))
    elif tipo == "mensagem_fisco":
        _renderizar_mensagem_fisco(b, payload, dims.line_width)
    elif tipo == "mensagem_empresa":
        _renderizar_mensagem_empresa(b, payload, tpl, dims.line_width)
    elif tipo == "texto":
        b.align(bloco.get("alinhamento", "left"))
        if bloco.get("negrito"):
            b.bold(True)
        for linha in str(bloco.get("texto", "")).splitlines():
            b.line(linha)
        if bloco.get("negrito"):
            b.bold(False)
    elif tipo == "separador":
        b.align("left").separator(str(bloco.get("caractere", "-"))[:1] or "-", dims.line_width)
    elif tipo == "espaco":
        b.feed(int(bloco.get("linhas", 1)))


def _renderizar_cabecalho(b: EscPosBuilder, payload: dict, tpl: dict, is_cupom: bool,
                           contingencia: bool, line_width: int) -> None:
    emitente = payload["emitente"]
    b.align("center").bold(True).line(emitente.get("razao_social", "")).bold(False)
    documento = f"CNPJ: {emitente['cnpj']}" if emitente.get("cnpj") else f"CPF: {emitente.get('cpf', '')}"
    if tpl["mostrar_ie"] and emitente.get("ie"):
        documento += f"  IE: {emitente['ie']}"
    b.line(documento)
    b.line(emitente.get("endereco", ""))
    if contingencia:
        _linhas_contingencia(b)
    b.separator("=", line_width)
    if is_cupom:
        b.line(tpl["cupom_titulo"])
    else:
        b.line("DANFE NFC-e - Documento Auxiliar da")
        b.line("Nota Fiscal de Consumidor Eletronica")
    if payload.get("ambiente") == "homologacao":
        b.bold(True).line(TEXTO_HOMOLOGACAO).bold(False)
    b.separator("-", line_width)


def _renderizar_atendente(b: EscPosBuilder, payload: dict, line_width: int) -> None:
    if not (payload.get("atendente") or payload.get("pdv_label")):
        return
    b.align("left")
    if payload.get("atendente"):
        b.line(f"Atendente: {payload['atendente']}")
    if payload.get("pdv_label"):
        b.line(f"Caixa: {payload['pdv_label']}")
    b.separator("-", line_width)


def _renderizar_itens(b: EscPosBuilder, payload: dict, dims: "_Dimensoes") -> None:
    b.align("left")
    for item in payload.get("itens", []):
        codigo = item.get("codigo", "")
        descricao = f"{codigo} {item['descricao']}".strip()
        for linha in _quebrar_por_palavra(descricao, dims.line_width):
            b.line(linha)
        qtd = item["quantidade"]
        unit = item["unidade"]
        v_unit = format_brl(item["valor_unitario"])
        v_total = item["valor_total"]
        b.line(f"{qtd} {unit} x {v_unit}".ljust(dims.left_col) + f"{format_brl(v_total):>{dims.value_col}}")


def _renderizar_totais(b: EscPosBuilder, payload: dict, dims: "_Dimensoes") -> None:
    b.separator("-", dims.line_width)
    totais = payload["totais"]
    b.line(f"{'Qtde. total de itens':<{dims.left_col}}{len(payload.get('itens', [])):>{dims.value_col}}")
    b.line(f"{'Valor total R$':<{dims.left_col}}{format_brl(totais['valor_produtos']):>{dims.value_col}}")
    acrescimos = (totais.get("valor_frete") or 0) + (totais.get("valor_seguro") or 0) + (totais.get("valor_outras_despesas") or 0)
    if acrescimos:
        b.line(f"{'Acrescimos R$':<{dims.left_col}}{format_brl(acrescimos):>{dims.value_col}}")
    if totais.get("valor_descontos"):
        b.line(f"{'Desconto R$':<{dims.left_col}}{format_brl(-totais['valor_descontos']):>{dims.value_col}}")
    b.bold(True).line(f"{'VALOR A PAGAR R$':<{dims.left_col}}{format_brl(totais['valor_total']):>{dims.value_col}}").bold(False)


def _renderizar_pagamentos(b: EscPosBuilder, payload: dict, dims: "_Dimensoes") -> None:
    if not payload.get("pagamentos"):
        return
    b.separator("-", dims.line_width)
    for pagamento in payload["pagamentos"]:
        b.line(f"{pagamento['forma']:<{dims.left_col}}{format_brl(pagamento['valor']):>{dims.value_col}}")
    if payload.get("troco"):
        b.line(f"{'Troco':<{dims.left_col}}{format_brl(payload['troco']):>{dims.value_col}}")


def _renderizar_divisao_fiscal(b: EscPosBuilder, payload: dict, dims: "_Dimensoes",
                                contingencia: bool, tpl: dict) -> None:
    """Divisões IV, V e VII — exclusivas de nota fiscal, nunca chamadas pro
    cupom (ver render_danfe_nfce)."""
    b.separator("=", dims.line_width)
    b.align("center")
    if payload.get("url_consulta_chave"):
        b.line("Consulte pela Chave de Acesso em")
        b.line(payload["url_consulta_chave"][:dims.line_width])
    b.line("Chave de acesso:")
    b.line(_format_chave_acesso(payload["chave_acesso"]))

    if payload.get("numero"):
        b.line(f"NFC-e no {payload['numero']}  Serie {payload.get('serie', '')}")
    if payload.get("data_emissao"):
        b.line(payload["data_emissao"])
    if contingencia:
        _linhas_contingencia(b)
    else:
        if payload.get("protocolo_autorizacao"):
            b.line(f"Protocolo de autorizacao: {payload['protocolo_autorizacao']}")
        if payload.get("data_hora_autorizacao"):
            b.line(payload["data_hora_autorizacao"])
    if payload.get("via") == 2:
        b.bold(True).line("Via do Estabelecimento").bold(False)

    if payload.get("qrcode_url"):
        b.feed(1)
        b.qr_code(payload["qrcode_url"], module_size=tpl["qr_module_size"],
                   error_correction=tpl["qr_error_correction"])


def _renderizar_mensagem_fisco(b: EscPosBuilder, payload: dict, line_width: int) -> None:
    mensagem = payload.get("mensagem_fisco")
    if mensagem:
        b.separator("-", line_width)
        b.align("left").line(mensagem)


def _renderizar_mensagem_empresa(b: EscPosBuilder, payload: dict, tpl: dict, line_width: int) -> None:
    mensagem = payload.get("mensagem_empresa") or payload.get("mensagem_adicional") or tpl.get("mensagem_empresa")
    if mensagem:
        b.separator("-", line_width)
        b.align("left").line(mensagem)


def _linha_consumidor(consumidor: dict) -> str:
    documento = consumidor.get("cpf_cnpj")
    if not documento:
        return "CONSUMIDOR NAO IDENTIFICADO"
    digitos = "".join(ch for ch in documento if ch.isdigit())
    rotulo = "CPF" if len(digitos) <= 11 else "CNPJ"
    return f"CONSUMIDOR {rotulo}: {documento}"


def _linhas_contingencia(b: EscPosBuilder) -> None:
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
