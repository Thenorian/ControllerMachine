"""
Renderização do DANFE-NFCe e do Cupom não fiscal (o comprovante impresso
depois que a venda foi concluída — DANFE só depois que a nota já foi
autorizada pela SEFAZ). Este módulo NÃO emite nem assina nota — isso é
responsabilidade do Simple ERP (ou de um provedor tipo Focus NFe). O Simple
ERP (ou quem tiver embutido o `server/`) manda DADOS da venda (payload
abaixo) num canal, e o LAYOUT (cabeçalho extra, mensagem padrão, tamanho
do QR, e no cupom até a ordem/composição do documento) — o `template` —
em outro: o Controller Machine nunca decide layout por conta própria, só
aplica o que foi empurrado por último (job `set_template`, ver
server/connector.py::send_template_update e
main.py::_dispatch_set_template/catalog.py::set_device_template). O
`template` fica cacheado em device["settings"]["template"] no config.json
local só pra continuar imprimindo se a conexão cair — não é editado à mão
aqui, e mudar uma regra fiscal ou o leiaute é um push pra cada controller
da empresa, nunca ida loja por loja.

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
        "itens": [{"codigo", "descricao", "unidade", "quantidade", "valor_unitario", "valor_total"}],
        "totais": {"valor_produtos", "valor_descontos", "valor_total", "valor_frete", "valor_seguro", "valor_outras_despesas"},
        "pagamentos": [{"forma", "valor"}],
        "troco": 0,
        "mensagem_fisco": "opcional — infAdFisco/xMsg (Divisão VIII)",
        "mensagem_empresa": "opcional — infCpl / recado do lojista (Divisão IX) desta venda específica",
    }

Contrato do TEMPLATE (ver DEFAULT_TEMPLATE abaixo) — recebido por push
(`set_template`), cacheado em device["settings"]["template"] no
config.json, nunca no payload. Inclui "pdv_label" (nome do caixa/PDV, ex.:
"PDV 1") — de propósito NÃO vem do payload da venda nem do nome do
dispositivo de impressão cadastrado: é uma identificação própria do posto
físico, e some da nota quando vazia (ver _renderizar_atendente).
"header_text"/"footer_text"/"mensagem_empresa" aceitam os placeholders
listados em `_contexto_template` (abaixo) e a sintaxe {"x"*N} pra repetir
caractere — ver devices/template_text.py.
"""
from __future__ import annotations

import base64

from devices.escpos import EscPosBuilder, chars_per_line, format_brl
from devices.template_text import renderizar as renderizar_template_texto

TEXTO_HOMOLOGACAO = "EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
TEXTO_CONTINGENCIA = ("EMITIDA EM CONTINGENCIA", "Pendente de autorizacao")

# Chaves que o template pode trazer. Qualquer uma que faltar usa o valor
# abaixo — controller que ainda não recebeu nenhum push continua imprimindo
# o padrão de fábrica.
DEFAULT_TEMPLATE = {
    "header_text": "",
    "header_bold": False,
    "header_align": "center",
    "footer_text": "",
    "footer_bold": False,
    "footer_align": "center",
    "mostrar_ie": True,
    "mensagem_empresa": "",       # fallback fixo se a venda não trouxer mensagem_empresa própria
    "mensagem_empresa_bold": False,
    "mensagem_empresa_align": "left",
    "qr_module_size": 6,
    "qr_error_correction": "M",
    "cupom_titulo": "CUPOM - SEM VALOR FISCAL",
    "pdv_label": "",       # nome do caixa/PDV - nunca o nome do dispositivo de impressão
    "fonte_pequena": True,  # Font B (ESC/POS) - condensada por padrão, economiza bobina
    # Modo Avançado (só cupom). Lista de blocos que SUBSTITUI o documento
    # padrão inteiro quando presente. IMPORTANTE: nota fiscal
    # (tipo_documento="nfce") NUNCA lê esta chave — a trava não é validação,
    # é estrutural (ver render_danfe_nfce abaixo), não tem como um template
    # mal configurado (nem um push malformado) tirar QR/chave/protocolo/
    # consumidor de uma NFC-e.
    "blocos_customizados": None,
}

# Vocabulário de blocos do Modo Avançado — de propósito NÃO existe bloco de
# QR Code, chave de acesso, protocolo, número ou série: essas peças são
# exclusivas do fluxo fiscal fixo, nem aparecem como opção pra montar um
# cupom customizado. "codigo_barras"/"abrir_gaveta"/"raw" existem pra dar
# acesso a qualquer comando ESC/POS que o builder não modele por um bloco
# dedicado (ver devices/escpos.py) — "raw" é a válvula de escape final,
# bytes crus em base64, pensada pra quem sabe exatamente que sequência
# quer mandar (comando proprietário de fabricante, por exemplo).
TIPOS_BLOCO_VALIDOS = {
    "cabecalho", "atendente", "itens", "totais", "pagamentos", "consumidor",
    "mensagem_empresa", "mensagem_fisco", "texto", "separador", "espaco",
    "codigo_barras", "abrir_gaveta", "raw",
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
    dims = _Dimensoes(paper_width_mm, tpl["fonte_pequena"])
    b = EscPosBuilder(encoding=encoding, plain=(mode == "raw"))
    b.font(small=tpl["fonte_pequena"])
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

    def __init__(self, paper_width_mm: int, fonte_pequena: bool = False):
        self.line_width = chars_per_line(paper_width_mm, fonte_pequena)
        self.value_col = 10  # cabe "-9999999.99" folgado, mesma coluna nos dois tamanhos de bobina
        self.left_col = self.line_width - self.value_col


def _renderizar_documento_padrao(b: EscPosBuilder, payload: dict, tpl: dict, is_cupom: bool,
                                  contingencia: bool, dims: "_Dimensoes") -> None:
    """Fluxo fixo — usado sempre pra nota fiscal, e pro cupom quando o Modo
    Avançado não tiver definido blocos_customizados (Modo Básico)."""
    contexto = _contexto_template(payload, tpl)

    if tpl["header_text"]:
        b.align(tpl.get("header_align", "center"))
        if tpl.get("header_bold"):
            b.bold(True)
        for line in renderizar_template_texto(tpl["header_text"], contexto, dims.line_width):
            b.line(line)
        if tpl.get("header_bold"):
            b.bold(False)
        b.separator("-", dims.line_width)

    _renderizar_cabecalho(b, payload, tpl, is_cupom, contingencia, dims.line_width)
    _renderizar_atendente(b, payload, tpl, dims.line_width)
    _renderizar_itens(b, payload, dims)
    _renderizar_totais(b, payload, dims)
    _renderizar_pagamentos(b, payload, dims)

    b.separator("-", dims.line_width)
    b.align("left").line(_linha_consumidor(payload.get("consumidor") or {}))

    if not is_cupom:
        _renderizar_divisao_fiscal(b, payload, dims, contingencia, tpl)

    _renderizar_mensagem_fisco(b, payload, dims.line_width)
    _renderizar_mensagem_empresa(b, payload, tpl, contexto, dims.line_width)

    if tpl["footer_text"]:
        b.separator("-", dims.line_width)
        b.align(tpl.get("footer_align", "center"))
        if tpl.get("footer_bold"):
            b.bold(True)
        for line in renderizar_template_texto(tpl["footer_text"], contexto, dims.line_width):
            b.line(line)
        if tpl.get("footer_bold"):
            b.bold(False)


def _renderizar_bloco(b: EscPosBuilder, bloco: dict, payload: dict, tpl: dict,
                       dims: "_Dimensoes", is_cupom: bool, contingencia: bool) -> None:
    """Modo Avançado (só cupom) — cada bloco da lista `blocos_customizados`
    vira uma chamada aqui. Tipo desconhecido/inválido é ignorado (nunca
    derruba a impressão inteira por um bloco malformado)."""
    tipo = bloco.get("tipo")
    if tipo not in TIPOS_BLOCO_VALIDOS:
        return

    if tipo == "cabecalho":
        _renderizar_cabecalho(b, payload, tpl, is_cupom, contingencia, dims.line_width)
    elif tipo == "atendente":
        _renderizar_atendente(b, payload, tpl, dims.line_width)
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
        _renderizar_mensagem_empresa(b, payload, tpl, _contexto_template(payload, tpl), dims.line_width)
    elif tipo == "texto":
        b.align(bloco.get("alinhamento", "left"))
        if bloco.get("negrito"):
            b.bold(True)
        if bloco.get("sublinhado"):
            b.underline(True)
        if bloco.get("inverter"):
            b.invert(True)
        tamanho = bloco.get("tamanho")
        if tamanho:
            largura, altura = (tamanho, tamanho) if isinstance(tamanho, int) else tuple(tamanho[:2])
            b.size(largura, altura)
        contexto = _contexto_template(payload, tpl)
        for linha in renderizar_template_texto(str(bloco.get("texto", "")), contexto, dims.line_width):
            b.line(linha)
        if tamanho:
            b.size(1, 1)
        if bloco.get("inverter"):
            b.invert(False)
        if bloco.get("sublinhado"):
            b.underline(False)
        if bloco.get("negrito"):
            b.bold(False)
    elif tipo == "separador":
        b.align("left").separator(str(bloco.get("caractere", "-"))[:1] or "-", dims.line_width)
    elif tipo == "espaco":
        b.feed(int(bloco.get("linhas", 1)))
    elif tipo == "codigo_barras":
        b.align(bloco.get("alinhamento", "center"))
        b.barcode(
            str(bloco.get("dados", "")),
            symbology=bloco.get("simbologia", "code128"),
            height=int(bloco.get("altura", 60)),
            module_width=int(bloco.get("largura_modulo", 2)),
            hri=bloco.get("hri", "below"),
        )
    elif tipo == "abrir_gaveta":
        b.cash_drawer_kick(pin=int(bloco.get("pino", 0)))
    elif tipo == "raw":
        try:
            b.raw(base64.b64decode(bloco.get("dados_base64", "")))
        except (ValueError, TypeError):
            pass  # base64 malformado — ignora, mesma regra de bloco inválido


def _renderizar_cabecalho(b: EscPosBuilder, payload: dict, tpl: dict, is_cupom: bool,
                           contingencia: bool, line_width: int) -> None:
    emitente = payload["emitente"]
    if emitente.get("razao_social"):
        b.align("center").bold(True).line(emitente["razao_social"]).bold(False)

    # Cada campo só ocupa linha quando tem valor de verdade - nada de linha
    # em branco (nem texto tipo "Ausente") pra CNPJ/CPF/IE/endereço vazio,
    # senão o cabeçalho fica maior à toa numa bobina que já é estreita.
    documento = f"CNPJ: {emitente['cnpj']}" if emitente.get("cnpj") else (
        f"CPF: {emitente['cpf']}" if emitente.get("cpf") else ""
    )
    if tpl["mostrar_ie"] and emitente.get("ie"):
        documento = f"{documento}  IE: {emitente['ie']}" if documento else f"IE: {emitente['ie']}"
    if documento:
        b.line(documento)
    if emitente.get("endereco"):
        b.line(emitente["endereco"])
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


def _renderizar_atendente(b: EscPosBuilder, payload: dict, tpl: dict, line_width: int) -> None:
    # pdv_label vem do TEMPLATE (configurado aqui no Controller Machine) —
    # nunca do payload do Simple ERP nem do nome do dispositivo de impressão
    # cadastrado. Some da nota quando vazio (ver DEFAULT_TEMPLATE).
    pdv_label = tpl.get("pdv_label") or ""
    if not (payload.get("atendente") or pdv_label):
        return
    b.align("left")
    if payload.get("atendente"):
        b.line(f"Atendente: {payload['atendente']}")
    if pdv_label:
        b.line(f"Caixa: {pdv_label}")
    b.separator("-", line_width)


def _renderizar_itens(b: EscPosBuilder, payload: dict, dims: "_Dimensoes") -> None:
    """Cada item vira 2 linhas — código de barras + nome (quebrado por
    palavra) na primeira, quantidade x valor unitário à esquerda e valor
    total à direita na segunda. Uma "tabela" de 5 colunas de verdade (tudo
    numa linha só) não cabe legível nas larguras de bobina suportadas (32 a
    64 colunas, ver escpos.CHARS_PER_LINE*) — esse layout em 2 linhas é o
    padrão de mercado pra cupom térmico exatamente por isso."""
    b.align("left")
    for item in payload.get("itens", []):
        codigo = item.get("codigo", "")
        descricao = f"{codigo}  {item['descricao']}".strip()
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


def _renderizar_mensagem_empresa(b: EscPosBuilder, payload: dict, tpl: dict, contexto: dict, line_width: int) -> None:
    mensagem = payload.get("mensagem_empresa") or payload.get("mensagem_adicional") or tpl.get("mensagem_empresa")
    if mensagem:
        b.separator("-", line_width)
        b.align(tpl.get("mensagem_empresa_align", "left"))
        if tpl.get("mensagem_empresa_bold"):
            b.bold(True)
        for linha in renderizar_template_texto(mensagem, contexto, line_width):
            b.line(linha)
        if tpl.get("mensagem_empresa_bold"):
            b.bold(False)


def _contexto_template(payload: dict, tpl: dict) -> dict:
    """Placeholders disponíveis pros campos de texto livre (cabeçalho,
    rodapé, mensagem da empresa) via {{campo}} — ver devices/template_text.py
    (motor). Lista de chaves abaixo é a documentação de quem for montar o
    template do lado de fora (ver server/templates.py::Text)."""
    emitente = payload.get("emitente") or {}
    totais = payload.get("totais") or {}
    return {
        "razao_social": emitente.get("razao_social", ""),
        "cnpj": emitente.get("cnpj", ""),
        "cpf": emitente.get("cpf", ""),
        "ie": emitente.get("ie", ""),
        "endereco": emitente.get("endereco", ""),
        "atendente": payload.get("atendente", ""),
        "pdv_label": tpl.get("pdv_label") or "",
        "numero": payload.get("numero", ""),
        "serie": payload.get("serie", ""),
        "data_emissao": payload.get("data_emissao", ""),
        "chave_acesso": payload.get("chave_acesso", ""),
        "protocolo_autorizacao": payload.get("protocolo_autorizacao", ""),
        "valor_total": format_brl(totais.get("valor_total", 0)),
        "valor_produtos": format_brl(totais.get("valor_produtos", 0)),
    }


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
