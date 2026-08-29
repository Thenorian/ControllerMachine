"""
Editor de modelo de impressão — Modo Básico (embutido no formulário de
dispositivo, gui/window.py::DeviceDialog) e Modo Avançado (editor de blocos
livre, só pro cupom). Configura o `template` consumido por
devices/printer_fiscal.py::render_danfe_nfce — vive só aqui, 100% local:
o Simple ERP nunca vê nem edita nada de layout (ver README, seção "Modelo
de impressão").

Segurança do Modo Avançado é estrutural, não deste módulo — o renderer
(printer_fiscal.py) só lê blocos_customizados quando tipo_documento="cupom",
nunca pra nota fiscal, e o vocabulário de blocos (TIPOS_BLOCO_VALIDOS) não
tem QR Code/chave de acesso/protocolo como opção. Este módulo só cuida da
interface e do log da alteração.
"""
from __future__ import annotations

import json
import logging
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from devices.escpos import chars_per_line
from devices.printer_fiscal import DEFAULT_TEMPLATE, TIPOS_BLOCO_VALIDOS, render_danfe_nfce

logger = logging.getLogger("template_editor")

# Placeholders aceitos em Cabeçalho/Rodapé/Mensagem da empresa — ver
# devices/template_text.py (motor) e devices/printer_fiscal.py::
# _contexto_template (de onde vem o valor de cada um). Mantido em sincronia
# manualmente com aquela função — um é o motor, este é a documentação/UI.
CAMPOS_DISPONIVEIS = (
    "razao_social", "cnpj", "cpf", "ie", "endereco", "atendente", "pdv_label",
    "numero", "serie", "data_emissao", "chave_acesso", "protocolo_autorizacao",
    "valor_total", "valor_produtos",
)
AJUDA_TEMPLATE = (
    "Use {{campo}} pra inserir um dado (ex.: {{razao_social}}) e {\"-\"*20} "
    "pra repetir um caractere (ex.: uma linha de traços). Campos disponíveis: "
    + ", ".join(f"{{{{{c}}}}}" for c in CAMPOS_DISPONIVEIS)
)

# Dado fictício só pra pré-visualização — nunca é impresso de verdade, existe
# só pra mostrar como o modelo fica na bobina enquanto edita.
_PREVIEW_PAYLOAD = {
    "tipo_documento": "nfce",
    "chave_acesso": "0" * 44,
    "ambiente": "homologacao",
    "numero": "1", "serie": "1", "data_emissao": "29/08/2026 10:00:00",
    "protocolo_autorizacao": "123456789012345", "data_hora_autorizacao": "29/08/2026 10:00:05",
    "url_consulta_chave": "www.nfce.fazenda.gov.br",
    "qrcode_url": "https://exemplo.com",
    "emitente": {
        "cnpj": "00.000.000/0001-00", "razao_social": "Empresa Exemplo LTDA",
        "ie": "123.456.789", "endereco": "Rua Exemplo, 123 - Centro",
    },
    "consumidor": {},
    "atendente": "Funcionario de Exemplo",
    "itens": [
        {"codigo": "7891234567890", "descricao": "Produto de exemplo", "unidade": "UN",
         "quantidade": 2, "valor_unitario": 10.0, "valor_total": 20.0},
    ],
    "totais": {"valor_produtos": 20.0, "valor_descontos": 0, "valor_total": 20.0},
    "pagamentos": [{"forma": "Dinheiro", "valor": 20.0}],
    "troco": 0,
}

# Ordem de exibição no seletor "Adicionar bloco" — texto/separador/espaço
# primeiro (o que a maioria vai usar), depois os blocos que puxam dado real
# da venda.
BLOCK_LABELS = {
    "texto": "Texto livre",
    "separador": "Linha separadora",
    "espaco": "Espaço em branco",
    "cabecalho": "Cabeçalho da empresa",
    "atendente": "Atendente / Caixa",
    "itens": "Itens da venda",
    "totais": "Totais",
    "pagamentos": "Pagamentos",
    "consumidor": "Identificação do consumidor",
    "mensagem_empresa": "Mensagem da empresa",
    "mensagem_fisco": "Mensagem do Fisco",
}
_LABEL_POR_TIPO = {v: k for k, v in BLOCK_LABELS.items()}
_TIPOS_COM_TEXTO_LIVRE = {"texto", "separador", "espaco"}

# Ponto de partida quando o Modo Avançado é aberto pela 1ª vez (sem nada
# customizado ainda) — mesma composição do fluxo padrão do cupom, só que
# editável a partir daqui.
_BLOCOS_PADRAO_CUPOM = [
    {"tipo": "cabecalho"}, {"tipo": "atendente"}, {"tipo": "itens"},
    {"tipo": "totais"}, {"tipo": "pagamentos"}, {"tipo": "consumidor"},
    {"tipo": "mensagem_fisco"}, {"tipo": "mensagem_empresa"},
]

AVISO_TEXTO = (
    "Esta área é reservada à equipe Thenorian.\n\n"
    "Toda alteração feita aqui fica registrada em log com data e hora.\n\n"
    "Mudanças feitas sem autorização prévia podem ser cobradas e têm "
    "implicação FISCAL — mexa aqui só se souber exatamente o que está "
    "fazendo."
)


def _blocos_validos(blocos) -> list[dict]:
    """Filtra uma lista de blocos crua (ex.: vinda de um .json importado) —
    descarta silenciosamente qualquer item que não seja um dict com um
    "tipo" reconhecido, em vez de deixar isso quebrar a listbox do editor
    ou (pior) o job de impressão real mais tarde."""
    if not isinstance(blocos, list):
        return []
    return [b for b in blocos if isinstance(b, dict) and b.get("tipo") in TIPOS_BLOCO_VALIDOS]


def _bloco_descricao(bloco: dict) -> str:
    tipo = bloco.get("tipo")
    label = BLOCK_LABELS.get(tipo, tipo)
    if tipo == "texto":
        primeira_linha = (bloco.get("texto") or "").splitlines()[0] if bloco.get("texto") else ""
        return f'{label}: "{primeira_linha[:40]}"'
    if tipo == "separador":
        return f'{label} ("{bloco.get("caractere", "-")}")'
    if tipo == "espaco":
        return f'{label} ({bloco.get("linhas", 1)} linha(s))'
    return label


class TemplateBasicFrame(ttk.LabelFrame):
    """Modo Básico — campos direto no formulário de editar dispositivo.
    Cabeçalho/Rodapé/Mensagem da empresa aceitam os placeholders/repetição
    de devices/template_text.py (ver CAMPOS_DISPONIVEIS/AJUDA_TEMPLATE)."""

    _MONO_FONT = ("Consolas", 9)

    def __init__(self, parent, get_paper_width_mm):
        """get_paper_width_mm: callable que devolve a largura de bobina (mm)
        atualmente selecionada no resto do formulário (window.py::DeviceDialog)
        — usada só pra dimensionar os campos de texto e a pré-visualização,
        nunca guardada aqui (sempre lê o valor mais atual do resto do
        formulário, inclusive depois de trocar a bobina sem fechar o diálogo)."""
        super().__init__(parent, text="Modelo de impressão", padding=6)
        self._get_paper_width_mm = get_paper_width_mm
        self._blocos_customizados: list[dict] | None = None  # só o Modo Avançado mexe nisso

        row = 0
        self.mostrar_ie_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Mostrar Inscrição Estadual (IE)", variable=self.mostrar_ie_var,
                        command=self._refresh_preview).grid(row=row, column=0, columnspan=4, sticky="w")
        row += 1

        ttk.Label(self, text="Título do cupom:").grid(row=row, column=0, sticky="w", pady=(4, 0))
        self.cupom_titulo_entry = ttk.Entry(self, width=32)
        self.cupom_titulo_entry.grid(row=row, column=1, columnspan=3, sticky="we", padx=(4, 0), pady=(4, 0))
        self.cupom_titulo_entry.bind("<KeyRelease>", lambda _e: self._refresh_preview())
        row += 1

        ttk.Label(self, text="Cabeçalho:").grid(row=row, column=0, sticky="nw", pady=(4, 0))
        self.header_text = self._novo_campo_texto(row)
        row += 1

        ttk.Label(self, text="Rodapé:").grid(row=row, column=0, sticky="nw", pady=(4, 0))
        self.footer_text = self._novo_campo_texto(row)
        row += 1

        ttk.Label(self, text="Mensagem padrão da empresa:").grid(row=row, column=0, sticky="nw", pady=(4, 0))
        self.mensagem_empresa_text = self._novo_campo_texto(row)
        row += 1

        ttk.Label(self, text=AJUDA_TEMPLATE, foreground="#555", wraplength=360, justify="left").grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )
        row += 1

        ttk.Label(self, text="QR Code — módulo:").grid(row=row, column=0, sticky="w", pady=(4, 0))
        self.qr_module_spin = ttk.Spinbox(self, from_=1, to=16, width=5, command=self._refresh_preview)
        self.qr_module_spin.grid(row=row, column=1, sticky="w", padx=(4, 16), pady=(4, 0))
        self.qr_module_spin.bind("<KeyRelease>", lambda _e: self._refresh_preview())
        ttk.Label(self, text="Correção de erro:").grid(row=row, column=2, sticky="w", pady=(4, 0))
        self.qr_ec_combo = ttk.Combobox(self, values=["L", "M", "Q", "H"], state="readonly", width=4)
        self.qr_ec_combo.grid(row=row, column=3, sticky="w", padx=(4, 0), pady=(4, 0))
        self.qr_ec_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_preview())
        row += 1

        # Campos adicionais — de propósito por último: os principais do
        # formulário são os da venda (cabeçalho/itens/totais/etc., fixos ou
        # definidos acima); estes dois são só metadado do posto físico onde
        # a impressora está instalada, não da venda em si.
        ttk.Separator(self, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="we", pady=(8, 4))
        row += 1
        ttk.Label(self, text="Campos adicionais", foreground="#555").grid(row=row, column=0, columnspan=4, sticky="w")
        row += 1

        ttk.Label(self, text="Nome do PDV/Caixa:").grid(row=row, column=0, sticky="w", pady=(4, 0))
        self.pdv_label_entry = ttk.Entry(self, width=24)
        self.pdv_label_entry.grid(row=row, column=1, sticky="w", padx=(4, 0), pady=(4, 0))
        self.pdv_label_entry.bind("<KeyRelease>", lambda _e: self._refresh_preview())
        ttk.Label(self, text="(nunca o nome do dispositivo — some da nota se vazio)",
                  foreground="#888").grid(row=row, column=2, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        self.fonte_pequena_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Fonte reduzida (cabe mais texto por linha)",
                        variable=self.fonte_pequena_var, command=self._on_fonte_changed).grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(4, 0)
        )
        row += 1

        ttk.Button(self, text="Modo Avançado (cupom)...", command=self._open_advanced).grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )
        row += 1
        self.advanced_status = ttk.Label(self, text="", foreground="#a15c00")
        self.advanced_status.grid(row=row, column=0, columnspan=4, sticky="w")
        row += 1

        io_row = ttk.Frame(self)
        io_row.grid(row=row, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Button(io_row, text="Exportar modelo...", command=self._export).pack(side="left")
        ttk.Button(io_row, text="Importar modelo...", command=self._import).pack(side="left", padx=(6, 0))
        row += 1

        ttk.Label(self, text="Pré-visualização:").grid(row=row, column=0, columnspan=4, sticky="w", pady=(10, 0))
        row += 1
        self.preview_text = tk.Text(self, height=16, font=self._MONO_FONT, state="disabled",
                                     background="#f5f5f0")
        self.preview_text.grid(row=row, column=0, columnspan=4, sticky="we", pady=(2, 0))

    def _novo_campo_texto(self, row: int) -> tk.Text:
        widget = tk.Text(self, height=3, font=self._MONO_FONT)
        widget.grid(row=row, column=1, columnspan=3, sticky="we", padx=(4, 0), pady=(4, 0))
        widget.bind("<KeyRelease>", lambda _e: self._refresh_preview())
        return widget

    def _on_fonte_changed(self) -> None:
        self._ajustar_largura_campos()
        self._refresh_preview()

    def on_paper_changed(self) -> None:
        """Chamado de fora (window.py) quando o combo de bobina muda — a
        largura dos campos de texto e da pré-visualização precisa acompanhar,
        senão fica mostrando uma largura que não é mais a real."""
        self._ajustar_largura_campos()
        self._refresh_preview()

    def _ajustar_largura_campos(self) -> None:
        largura = chars_per_line(self._get_paper_width_mm(), self.fonte_pequena_var.get())
        for widget in (self.header_text, self.footer_text, self.mensagem_empresa_text, self.preview_text):
            widget.configure(width=largura)

    def load(self, template: dict) -> None:
        tpl = {**DEFAULT_TEMPLATE, **(template or {})}
        self.mostrar_ie_var.set(bool(tpl["mostrar_ie"]))
        self.cupom_titulo_entry.delete(0, tk.END)
        self.cupom_titulo_entry.insert(0, tpl["cupom_titulo"])
        self._set_text(self.header_text, tpl["header_text"])
        self._set_text(self.footer_text, tpl["footer_text"])
        self._set_text(self.mensagem_empresa_text, tpl["mensagem_empresa"])
        self.qr_module_spin.delete(0, tk.END)
        self.qr_module_spin.insert(0, str(tpl["qr_module_size"]))
        self.qr_ec_combo.set(tpl["qr_error_correction"])
        self.pdv_label_entry.delete(0, tk.END)
        self.pdv_label_entry.insert(0, tpl["pdv_label"])
        self.fonte_pequena_var.set(bool(tpl["fonte_pequena"]))
        self._blocos_customizados = _blocos_validos(tpl.get("blocos_customizados")) or None
        self._update_advanced_status()
        self._ajustar_largura_campos()
        self._refresh_preview()

    @staticmethod
    def _set_text(widget: tk.Text, valor: str) -> None:
        widget.delete("1.0", tk.END)
        widget.insert("1.0", valor or "")

    def read(self) -> dict:
        try:
            qr_module_size = int(self.qr_module_spin.get())
        except ValueError:
            qr_module_size = DEFAULT_TEMPLATE["qr_module_size"]
        qr_module_size = max(1, min(16, qr_module_size))

        return {
            "mostrar_ie": self.mostrar_ie_var.get(),
            "cupom_titulo": self.cupom_titulo_entry.get().strip() or DEFAULT_TEMPLATE["cupom_titulo"],
            "header_text": self.header_text.get("1.0", "end-1c").strip(),
            "footer_text": self.footer_text.get("1.0", "end-1c").strip(),
            "mensagem_empresa": self.mensagem_empresa_text.get("1.0", "end-1c").strip(),
            "qr_module_size": qr_module_size,
            "qr_error_correction": self.qr_ec_combo.get() or "M",
            "pdv_label": self.pdv_label_entry.get().strip(),
            "fonte_pequena": self.fonte_pequena_var.get(),
            "blocos_customizados": self._blocos_customizados,
        }

    def _refresh_preview(self) -> None:
        """Reaproveita o renderer de verdade (render_danfe_nfce) num payload
        fictício — DRY: nunca duplica a lógica de layout aqui, então a
        pré-visualização nunca pode ficar dessincronizada do que realmente
        vai pra impressora."""
        template = self.read()
        try:
            raw = render_danfe_nfce(
                _PREVIEW_PAYLOAD, encoding="cp860", paper_width_mm=self._get_paper_width_mm(),
                mode="raw", cut_mode="none", template=template,
            )
            texto = raw.decode("cp860", errors="replace")
        except Exception as err:  # nunca deixa a pré-visualização travar o formulário
            texto = f"(pré-visualização indisponível: {err})"

        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", texto)
        self.preview_text.configure(state="disabled")

    def _update_advanced_status(self) -> None:
        if self._blocos_customizados:
            n = len(self._blocos_customizados)
            self.advanced_status.configure(text=f"Modo Avançado ativo no cupom ({n} bloco(s) customizado(s))")
        else:
            self.advanced_status.configure(text="")

    def _open_advanced(self) -> None:
        if not _AdvancedWarningDialog(self).accepted:
            return
        editor = _BlockEditorDialog(self, self._blocos_customizados)
        if editor.result is None:
            return  # cancelado

        antigo = self._blocos_customizados
        novo = editor.result or None
        if antigo != novo:
            logger.warning(
                "Modelo AVANÇADO do cupom alterado — %d bloco(s) antes, %d bloco(s) depois: %r -> %r",
                len(antigo or []), len(novo or []), antigo, novo,
            )
        self._blocos_customizados = novo
        self._update_advanced_status()
        self._refresh_preview()

    def _export(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self, title="Exportar modelo de impressão",
            defaultextension=".json", filetypes=[("Modelo JSON", "*.json")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.read(), f, ensure_ascii=False, indent=2)
        except OSError as err:
            messagebox.showerror("Exportar modelo", f"Falha ao salvar o arquivo: {err}", parent=self)
            return
        messagebox.showinfo("Exportar modelo", "Modelo exportado com sucesso.", parent=self)

    def _import(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Importar modelo de impressão",
            filetypes=[("Modelo JSON", "*.json")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                template = json.load(f)
        except (OSError, json.JSONDecodeError) as err:
            messagebox.showerror("Importar modelo", f"Arquivo inválido: {err}", parent=self)
            return
        if not isinstance(template, dict):
            messagebox.showerror("Importar modelo", "Arquivo inválido: não é um modelo de impressão.", parent=self)
            return

        antigo = self._blocos_customizados
        self.load(template)
        novo = self._blocos_customizados
        if antigo != novo:
            logger.warning(
                "Modelo AVANÇADO do cupom importado de %s — %d bloco(s) antes, %d bloco(s) depois: %r -> %r",
                path, len(antigo or []), len(novo or []), antigo, novo,
            )
        messagebox.showinfo("Importar modelo", "Modelo importado — revise os campos e salve o dispositivo.", parent=self)


class _AdvancedWarningDialog(tk.Toplevel):
    """Sem trava de permissão — só um aviso que precisa ser confirmado antes
    de liberar o editor. Ver AVISO_TEXTO."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Modo Avançado")
        self.resizable(False, False)
        self.accepted = False

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=AVISO_TEXTO, wraplength=360, justify="left",
                  foreground="#a10000").pack(anchor="w")

        self.confirm_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body, text="Li e entendo", variable=self.confirm_var,
            command=self._update_continue_state,
        ).pack(anchor="w", pady=(10, 0))

        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(14, 0))
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="left", padx=(0, 6))
        self.continue_button = ttk.Button(
            buttons, text="Entendi, continuar", command=self._continue, state="disabled"
        )
        self.continue_button.pack(side="left")

        self.transient(parent)
        self.grab_set()
        self.wait_window(self)

    def _update_continue_state(self) -> None:
        self.continue_button.configure(state="normal" if self.confirm_var.get() else "disabled")

    def _continue(self) -> None:
        self.accepted = True
        self.destroy()


class _BlockEditorDialog(tk.Toplevel):
    """Editor de blocos do cupom — reordenar, adicionar, editar, remover.
    `blocos_customizados` de entrada é a lista já salva (ou None pra
    começar a partir do fluxo padrão, editável)."""

    def __init__(self, parent, blocos_customizados: list[dict] | None):
        super().__init__(parent)
        self.title("Editor de blocos — Cupom (Modo Avançado)")
        self.resizable(False, False)
        self.result: list[dict] | None = None
        self._blocos = [dict(b) for b in (blocos_customizados or _BLOCOS_PADRAO_CUPOM)]

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body,
            text="A nota fiscal NUNCA usa este editor — a estrutura legal da "
                 "NFC-e é sempre fixa. Isto aqui é só pro CUPOM (documento "
                 "sem valor fiscal).",
            wraplength=420, justify="left", foreground="#555",
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        self.listbox = tk.Listbox(body, width=50, height=12, exportselection=False)
        self.listbox.grid(row=1, column=0, sticky="ns", pady=(8, 0))
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._sync_buttons())

        side = ttk.Frame(body)
        side.grid(row=1, column=1, sticky="n", padx=(8, 0), pady=(8, 0))
        ttk.Button(side, text="Adicionar...", command=self._add_block).pack(fill="x")
        self.edit_button = ttk.Button(side, text="Editar...", command=self._edit_block, state="disabled")
        self.edit_button.pack(fill="x", pady=(4, 0))
        self.remove_button = ttk.Button(side, text="Remover", command=self._remove_block, state="disabled")
        self.remove_button.pack(fill="x", pady=(4, 0))
        self.up_button = ttk.Button(side, text="Mover para cima", command=lambda: self._move(-1), state="disabled")
        self.up_button.pack(fill="x", pady=(12, 0))
        self.down_button = ttk.Button(side, text="Mover para baixo", command=lambda: self._move(1), state="disabled")
        self.down_button.pack(fill="x", pady=(4, 0))
        ttk.Button(side, text="Restaurar padrão", command=self._restaurar_padrao).pack(fill="x", pady=(20, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Salvar", command=self._salvar).pack(side="left")

        self._refresh_listbox()
        self.transient(parent)
        self.grab_set()
        self.wait_window(self)

    def _refresh_listbox(self) -> None:
        self.listbox.delete(0, tk.END)
        for bloco in self._blocos:
            self.listbox.insert(tk.END, _bloco_descricao(bloco))
        self._sync_buttons()

    def _selected_index(self) -> int | None:
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def _sync_buttons(self) -> None:
        idx = self._selected_index()
        has_sel = idx is not None
        editable = has_sel and self._blocos[idx]["tipo"] in _TIPOS_COM_TEXTO_LIVRE
        self.edit_button.configure(state="normal" if editable else "disabled")
        self.remove_button.configure(state="normal" if has_sel else "disabled")
        self.up_button.configure(state="normal" if has_sel and idx > 0 else "disabled")
        self.down_button.configure(state="normal" if has_sel and idx < len(self._blocos) - 1 else "disabled")

    def _add_block(self) -> None:
        bloco = _BlockPickerDialog(self).result
        if bloco:
            self._blocos.append(bloco)
            self._refresh_listbox()
            self.listbox.selection_set(len(self._blocos) - 1)
            self._sync_buttons()

    def _edit_block(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        bloco = _BlockPickerDialog(self, editing=self._blocos[idx]).result
        if bloco:
            self._blocos[idx] = bloco
            self._refresh_listbox()
            self.listbox.selection_set(idx)
            self._sync_buttons()

    def _remove_block(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        del self._blocos[idx]
        self._refresh_listbox()

    def _move(self, delta: int) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        novo = idx + delta
        if not (0 <= novo < len(self._blocos)):
            return
        self._blocos[idx], self._blocos[novo] = self._blocos[novo], self._blocos[idx]
        self._refresh_listbox()
        self.listbox.selection_set(novo)
        self._sync_buttons()

    def _restaurar_padrao(self) -> None:
        if messagebox.askyesno(
            "Restaurar padrão",
            "Isso descarta os blocos customizados e volta pro leiaute padrão do cupom. Continuar?",
            parent=self,
        ):
            self._blocos = []
            self._refresh_listbox()

    def _salvar(self) -> None:
        self.result = list(self._blocos)
        self.destroy()


class _BlockPickerDialog(tk.Toplevel):
    """Adicionar/editar um bloco — campos extras variam por tipo (texto
    livre, separador, espaço); os demais tipos só puxam dado real da venda,
    sem parâmetro nenhum pra configurar."""

    def __init__(self, parent, editing: dict | None = None):
        super().__init__(parent)
        self.title("Editar bloco" if editing else "Adicionar bloco")
        self.resizable(False, False)
        self.result: dict | None = None
        self._editing = editing

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Tipo:").grid(row=0, column=0, sticky="w")
        self.tipo_combo = ttk.Combobox(
            body, values=list(BLOCK_LABELS.values()),
            state="disabled" if editing else "readonly", width=28,
        )
        self.tipo_combo.set(BLOCK_LABELS.get((editing or {}).get("tipo", "texto"), "Texto livre"))
        self.tipo_combo.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.tipo_combo.bind("<<ComboboxSelected>>", lambda _e: self._build_extra_fields(None))

        self.extra_frame = ttk.Frame(body)
        self.extra_frame.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="OK", command=self._confirm).pack(side="left")

        self._build_extra_fields(editing)
        self.transient(parent)
        self.grab_set()
        self.wait_window(self)

    def _tipo_atual(self) -> str:
        return _LABEL_POR_TIPO.get(self.tipo_combo.get(), "texto")

    def _build_extra_fields(self, editing: dict | None) -> None:
        for w in self.extra_frame.winfo_children():
            w.destroy()
        tipo = editing["tipo"] if editing else self._tipo_atual()

        if tipo == "texto":
            ttk.Label(self.extra_frame, text="Texto:").grid(row=0, column=0, sticky="nw")
            self.texto_widget = tk.Text(self.extra_frame, width=36, height=3)
            self.texto_widget.grid(row=0, column=1, sticky="w", padx=(4, 0))
            if editing:
                self.texto_widget.insert("1.0", editing.get("texto", ""))

            ttk.Label(self.extra_frame, text="Alinhamento:").grid(row=1, column=0, sticky="w", pady=(4, 0))
            self.alinhamento_combo = ttk.Combobox(
                self.extra_frame, values=["left", "center", "right"], state="readonly", width=10
            )
            self.alinhamento_combo.set((editing or {}).get("alinhamento", "left"))
            self.alinhamento_combo.grid(row=1, column=1, sticky="w", padx=(4, 0), pady=(4, 0))

            self.negrito_var = tk.BooleanVar(value=(editing or {}).get("negrito", False))
            ttk.Checkbutton(self.extra_frame, text="Negrito", variable=self.negrito_var).grid(
                row=2, column=1, sticky="w", pady=(4, 0)
            )
        elif tipo == "separador":
            ttk.Label(self.extra_frame, text="Caractere:").grid(row=0, column=0, sticky="w")
            self.caractere_entry = ttk.Entry(self.extra_frame, width=4)
            self.caractere_entry.insert(0, (editing or {}).get("caractere", "-"))
            self.caractere_entry.grid(row=0, column=1, sticky="w", padx=(4, 0))
        elif tipo == "espaco":
            ttk.Label(self.extra_frame, text="Linhas:").grid(row=0, column=0, sticky="w")
            self.linhas_spin = ttk.Spinbox(self.extra_frame, from_=1, to=10, width=5)
            self.linhas_spin.delete(0, tk.END)
            self.linhas_spin.insert(0, str((editing or {}).get("linhas", 1)))
            self.linhas_spin.grid(row=0, column=1, sticky="w", padx=(4, 0))
        else:
            ttk.Label(
                self.extra_frame,
                text="Este bloco puxa o dado real da venda — sem opção extra pra configurar.",
                foreground="#555", wraplength=280, justify="left",
            ).grid(row=0, column=0, sticky="w")

    def _confirm(self) -> None:
        tipo = self._editing["tipo"] if self._editing else self._tipo_atual()
        bloco = {"tipo": tipo}
        if tipo == "texto":
            texto = self.texto_widget.get("1.0", "end").rstrip("\n")
            if not texto:
                messagebox.showwarning("Campo obrigatório", "Preencha o texto.", parent=self)
                return
            bloco["texto"] = texto
            bloco["alinhamento"] = self.alinhamento_combo.get() or "left"
            bloco["negrito"] = self.negrito_var.get()
        elif tipo == "separador":
            bloco["caractere"] = (self.caractere_entry.get().strip() or "-")[:1]
        elif tipo == "espaco":
            try:
                bloco["linhas"] = max(1, int(self.linhas_spin.get()))
            except ValueError:
                bloco["linhas"] = 1
        self.result = bloco
        self.destroy()
