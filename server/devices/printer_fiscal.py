"""
Renderização do DANFE-NFCe — ESC/POS. Isto SUBSTITUI, pra NFC-e, o
render_danfe_nfce que vivia em client/devices/printer_fiscal.py.

Motivo da mudança de lado (2026-09-16): o `client/` é o app instalado em
cada PC de loja - dar git push nesse repo não atualiza o executável já
rodando lá, então qualquer ajuste de layout feito só no client "não pega"
em produção sem alguém atualizar máquina por máquina. Este módulo mora em
`server/`, que é copiado direto pra dentro do Simple ERP (ver
server/connector.py) - sobe junto com o deploy normal do Simple ERP, sem
depender de atualização manual em loja nenhuma. client/devices/escpos.py e
printer_fiscal.py continuam existindo só pro Modo Avançado de CUPOM não
fiscal (blocos_customizados) - NFC-e nunca mais passa por lá.

O client, pra NFC-e, agora só recebe o buffer ESC/POS já pronto (job
data_type="escpos", ver client/main.py::_dispatch_fiscal) e entrega pra
impressora sem processar nada - é uma ponte, não um renderer.

Leiaute segue a especificação em Recursos/Documentação/Interna/Simple ERP/
NFCe.md (Obsidian) - Divisões I a IX do Manual de Especificações Técnicas
do DANFE NFC-e e QR Code. Revisar contra o Manual vigente antes de usar em
produção.

Contrato de entrada do PAYLOAD (o que o Simple ERP monta antes de chamar
render_danfe_nfce - MESMOS campos de antes, "emitente" ganhou campos novos
pro cabeçalho detalhado):

    {
        "chave_acesso": "44 dígitos",
        "protocolo_autorizacao": "...",
        "data_hora_autorizacao": "...",
        "ambiente": "producao" | "homologacao",
        "contingencia": False,
        "via": 1,                       # 2 = "Via do Estabelecimento"
        "numero": "...", "serie": "...", "data_emissao": "...",
        "url_consulta_chave": "...",
        "qrcode_url": "...",
        "emitente": {
            "cnpj", "cpf", "razao_social", "ie",       # "ie" vazio -> imprime "ISENTO"
            "logradouro",                              # já com número/complemento embutido
            "bairro", "cidade", "uf", "cep", "telefone",
            "endereco",                                # fallback se "logradouro" não vier
        },
        "consumidor": {"cpf_cnpj": "opcional"},
        "atendente": "opcional",
        "itens": [{"codigo", "descricao", "unidade", "quantidade", "valor_unitario", "valor_total"}],
        "totais": {"valor_produtos", "valor_descontos", "valor_total", "valor_frete", "valor_seguro", "valor_outras_despesas"},
        "pagamentos": [{"forma", "valor"}],
        "troco": 0,
        "mensagem_empresa": "opcional",
    }

TEMPLATE aceito (bem mais enxuto que o do client - NFC-e não tem Modo
Avançado nem header/footer de texto livre, é sempre este leiaute fixo):

    {"mostrar_ie": True, "mensagem_empresa": "", "qr_module_size": 5,
     "qr_error_correction": "M", "pdv_label": ""}
"""
from __future__ import annotations

from devices.escpos import EscPosBuilder, chars_per_line, format_brl

TEXTO_HOMOLOGACAO = "EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
TEXTO_CONTINGENCIA = ("EMITIDA EM CONTINGENCIA", "Pendente de autorizacao")
TITULO_NFCE = "Documento Auxiliar Da Nota Fiscal De Consumidor Eletrônica"

DEFAULT_TEMPLATE = {
    "mostrar_ie": True,
    "mensagem_empresa": "",
    "qr_module_size": 5,   # menor que o antigo (6) - Fonte B já libera espaço, QR não precisa ser grande
    "qr_error_correction": "M",
    "pdv_label": "",
    # Entrelinha em dots (ESC 3 n, ver escpos.py) - reduz a ALTURA de cada
    # linha, que é o que de fato encolhe o cupom (fonte B só muda largura
    # do caractere). 24 é notavelmente mais compacto que o default de
    # fábrica (~30-34 dots na maioria das Epson-compatíveis); ajustar aqui
    # se algum equipamento específico imprimir linhas grudadas demais.
    "entrelinha_dots": 24,
}


def render_danfe_nfce(payload: dict, encoding: str = "cp860", paper_width_mm: int = 80,
                       mode: str = "escpos", cut_mode: str = "full",
                       template: dict | None = None) -> bytes:
    for campo in ("emitente", "itens", "totais"):
        if campo not in payload:
            raise ValueError(f"payload de impressão fiscal incompleto — falta '{campo}'")
    if not payload.get("chave_acesso"):
        raise ValueError("payload de impressão fiscal incompleto — falta 'chave_acesso'")

    tpl = {**DEFAULT_TEMPLATE, **(template or {})}
    contingencia = bool(payload.get("contingencia"))
    larguras = _Larguras(paper_width_mm)

    b = EscPosBuilder(encoding=encoding, plain=(mode == "raw"))
    b.font(small=True)  # Fonte B é o padrão do corpo inteiro - só 2 trechos voltam pra Fonte A (ver abaixo)
    b.line_spacing(tpl["entrelinha_dots"])  # a altura da linha é o que de fato encolhe o cupom, não a fonte

    _cabecalho_emitente(b, payload, larguras, tpl, contingencia)
    _atendente(b, payload, tpl, larguras.b)
    _tabela_itens(b, payload["itens"], larguras.b)
    _totais(b, payload["totais"], larguras)
    _pagamentos(b, payload, larguras.b)

    b.align("left").separator("-", larguras.b)
    b.line(_linha_consumidor(payload.get("consumidor") or {})[:larguras.b])

    _bloco_fiscal_e_qr(b, payload, larguras.b, contingencia, tpl)
    _mensagem_empresa(b, payload, tpl, larguras.b)

    b.font(small=True).line_spacing(None)
    b.feed(3).cut(cut_mode)
    return b.build()


class _Larguras:
    """Colunas por linha na Fonte A (.a) e na Fonte B (.b) pra bobina dada -
    precisa das duas porque razão social e TOTAL trocam pra Fonte A por um
    instante (ver _cabecalho_emitente/_totais); uma linha formatada pra
    largura errada estoura/quebra feio quando a impressora troca de fonte."""

    def __init__(self, paper_width_mm: int):
        self.a = chars_per_line(paper_width_mm, fonte_pequena=False)
        self.b = chars_per_line(paper_width_mm, fonte_pequena=True)


class _ColunasItens:
    """Larguras fixas da tabela de itens - DESCRICAO absorve o espaço que
    sobrar depois das outras colunas, então cresce sozinha em bobina de
    80mm (mais coluna disponível) sem precisar de layout separado por
    tamanho de papel."""

    def __init__(self, largura_linha: int):
        estreita = largura_linha <= 42
        self.num = 2
        self.codigo = 6 if estreita else 8
        self.qtd = 5
        self.un = 2 if estreita else 3
        self.vunit = 7 if estreita else 9
        self.vtot = 8 if estreita else 10
        fixas = self.num + self.codigo + self.qtd + self.un + self.vunit + self.vtot
        separadores = 6  # 1 espaço entre cada uma das 7 colunas
        self.descricao = max(6, largura_linha - fixas - separadores)


def _cabecalho_emitente(b: EscPosBuilder, payload: dict, larguras: "_Larguras",
                         tpl: dict, contingencia: bool) -> None:
    emitente = payload["emitente"]
    b.align("center")

    if emitente.get("razao_social"):
        # Único trecho (junto com TOTAL) que volta pra Fonte A - destaque
        # pedido explicitamente, resto do cupom fica em Fonte B.
        b.font(small=False).bold(True)
        b.line(emitente["razao_social"].upper()[:larguras.a])
        b.bold(False).font(small=True)

    logradouro = emitente.get("logradouro") or emitente.get("endereco")
    if logradouro:
        linha_bairro = ", ".join(p for p in (logradouro, emitente.get("bairro")) if p)
        b.line(linha_bairro[:larguras.b])

    linha_cidade = _linha_cidade_uf_cep(emitente)
    if linha_cidade:
        b.line(linha_cidade[:larguras.b])

    if emitente.get("telefone"):
        b.line(f"Fone: {emitente['telefone']}"[:larguras.b])

    documento = _linha_documento(emitente, tpl)
    if documento:
        b.line(documento[:larguras.b])

    if contingencia:
        b.bold(True)
        for linha in TEXTO_CONTINGENCIA:
            b.line(linha)
        b.bold(False)

    b.separator("=", larguras.b)
    b.line(TITULO_NFCE[:larguras.b])
    if payload.get("ambiente") == "homologacao":
        b.bold(True).line(TEXTO_HOMOLOGACAO[:larguras.b]).bold(False)
    b.separator("-", larguras.b)


def _linha_cidade_uf_cep(emitente: dict) -> str:
    cidade_uf = "-".join(p for p in (emitente.get("cidade"), emitente.get("uf")) if p)
    partes = [p for p in (cidade_uf, emitente.get("cep")) if p]
    return "  ".join(partes)


def _linha_documento(emitente: dict, tpl: dict) -> str:
    documento = f"CNPJ: {emitente['cnpj']}" if emitente.get("cnpj") else (
        f"CPF: {emitente['cpf']}" if emitente.get("cpf") else ""
    )
    if tpl["mostrar_ie"]:
        # "ISENTO" é o valor fiscal correto pra empresa dispensada de IE -
        # nunca deixar a linha em branco nem repetir um placeholder de "vá
        # configurar" numa nota já emitida (ver routes/fiscal.py no Simple ERP).
        ie = emitente.get("ie") or "ISENTO"
        documento = f"{documento}  IE: {ie}" if documento else f"IE: {ie}"
    return documento


def _atendente(b: EscPosBuilder, payload: dict, tpl: dict, largura: int) -> None:
    pdv_label = tpl.get("pdv_label") or ""
    if not (payload.get("atendente") or pdv_label):
        return
    b.align("left")
    if payload.get("atendente"):
        b.line(f"Atendente: {payload['atendente']}"[:largura])
    if pdv_label:
        b.line(f"Caixa: {pdv_label}"[:largura])
    b.separator("-", largura)


def _tabela_itens(b: EscPosBuilder, itens: list[dict], largura: int) -> None:
    cols = _ColunasItens(largura)
    b.align("left")
    b.line(_linha_itens_cabecalho(cols))
    for idx, item in enumerate(itens, start=1):
        b.line(_linha_item(idx, item, cols))


def _linha_itens_cabecalho(cols: "_ColunasItens") -> str:
    return " ".join([
        "N".rjust(cols.num),
        "CODIGO".ljust(cols.codigo),
        "DESCRICAO".ljust(cols.descricao),
        "QTD".rjust(cols.qtd),
        "UN".ljust(cols.un),
        "V.UNIT".rjust(cols.vunit),
        "VL.TOT".rjust(cols.vtot),
    ])


def _linha_item(idx: int, item: dict, cols: "_ColunasItens") -> str:
    numero = str(idx)[:cols.num].rjust(cols.num)
    codigo = str(item.get("codigo") or "")[:cols.codigo].ljust(cols.codigo)
    descricao = str(item["descricao"])[:cols.descricao].ljust(cols.descricao)
    qtd = _formatar_qtd(item["quantidade"])[:cols.qtd].rjust(cols.qtd)
    unidade = str(item.get("unidade") or "UN")[:cols.un].ljust(cols.un)
    v_unit = format_brl(item["valor_unitario"])[:cols.vunit].rjust(cols.vunit)
    v_tot = format_brl(item["valor_total"])[:cols.vtot].rjust(cols.vtot)
    return " ".join([numero, codigo, descricao, qtd, unidade, v_unit, v_tot])


def _formatar_qtd(valor) -> str:
    valor = float(valor)
    if valor == int(valor):
        return str(int(valor))
    return f"{valor:.3f}".rstrip("0").rstrip(".")


def _totais(b: EscPosBuilder, totais: dict, larguras: "_Larguras") -> None:
    b.align("left").separator("-", larguras.b)
    b.line(_linha_valor("SUB TOTAL R$", totais["valor_produtos"], larguras.b))
    acrescimos = (totais.get("valor_frete") or 0) + (totais.get("valor_seguro") or 0) + (totais.get("valor_outras_despesas") or 0)
    if acrescimos:
        b.line(_linha_valor("ACRESCIMOS R$", acrescimos, larguras.b))
    if totais.get("valor_descontos"):
        b.line(_linha_valor("DESCONTO R$", -totais["valor_descontos"], larguras.b))

    # TOTAL: segundo (e último) trecho em Fonte A/bold - largura própria
    # (larguras.a), senão a linha formatada pra Fonte B estoura na hora que
    # a impressora troca pro caractere maior.
    b.font(small=False).bold(True)
    b.line(_linha_valor("TOTAL R$", totais["valor_total"], larguras.a))
    b.bold(False).font(small=True)


def _linha_valor(rotulo: str, valor: float, largura: int, largura_valor: int = 12) -> str:
    largura_valor = min(largura_valor, largura - 1) if largura > 1 else largura
    return f"{rotulo:<{largura - largura_valor}}{format_brl(valor):>{largura_valor}}"


def _pagamentos(b: EscPosBuilder, payload: dict, largura: int) -> None:
    pagamentos = payload.get("pagamentos") or []
    if not pagamentos:
        return
    b.align("left").separator("-", largura)
    for i, pagamento in enumerate(pagamentos, start=1):
        forma = str(pagamento["forma"]).upper()
        b.line(f"{i} - {forma} : {format_brl(pagamento['valor'])}"[:largura])
    if payload.get("troco"):
        b.line(f"TROCO : {format_brl(payload['troco'])}"[:largura])


def _bloco_fiscal_e_qr(b: EscPosBuilder, payload: dict, largura: int, contingencia: bool, tpl: dict) -> None:
    b.align("center").separator("=", largura)
    if payload.get("url_consulta_chave"):
        b.line("Consulte pela Chave de Acesso em")
        b.line(payload["url_consulta_chave"][:largura])
    b.line("Chave de acesso:")
    b.line(_format_chave_acesso(payload["chave_acesso"]))

    if payload.get("numero"):
        b.line(f"NFC-e no {payload['numero']}  Serie {payload.get('serie', '')}"[:largura])
    if payload.get("data_emissao"):
        b.line(payload["data_emissao"])

    if contingencia:
        b.bold(True)
        for linha in TEXTO_CONTINGENCIA:
            b.line(linha)
        b.bold(False)
    else:
        if payload.get("protocolo_autorizacao"):
            b.line(f"Protocolo de autorizacao: {payload['protocolo_autorizacao']}"[:largura])
        if payload.get("data_hora_autorizacao"):
            b.line(payload["data_hora_autorizacao"])
        b.line("EMISSAO NORMAL")

    if payload.get("via") == 2:
        b.bold(True).line("Via do Estabelecimento").bold(False)

    # QR abaixo do bloco de texto, centralizado, comando nativo (GS ( k) -
    # em ESC/POS não dá pra colocar texto e QR lado a lado (impressora
    # imprime linha a linha); ver docstring do módulo pra outras opções
    # consideradas e por que essa foi a escolhida.
    if payload.get("qrcode_url"):
        b.feed(1)
        b.qr_code(payload["qrcode_url"], module_size=tpl["qr_module_size"],
                   error_correction=tpl["qr_error_correction"])


def _mensagem_empresa(b: EscPosBuilder, payload: dict, tpl: dict, largura: int) -> None:
    mensagem = payload.get("mensagem_empresa") or tpl.get("mensagem_empresa")
    if not mensagem:
        return
    b.separator("-", largura).align("left")
    for linha in _quebrar_por_palavra(mensagem, largura):
        b.line(linha)


def _linha_consumidor(consumidor: dict) -> str:
    documento = consumidor.get("cpf_cnpj")
    if not documento:
        return "CONSUMIDOR NAO IDENTIFICADO"
    digitos = "".join(ch for ch in documento if ch.isdigit())
    rotulo = "CPF" if len(digitos) <= 11 else "CNPJ"
    return f"CONSUMIDOR {rotulo}: {documento}"


def _quebrar_por_palavra(texto: str, largura: int) -> list[str]:
    """Quebra por palavra (nunca corta uma palavra ao meio) - palavra maior
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
