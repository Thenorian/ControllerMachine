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

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from devices.printer_fiscal import DEFAULT_TEMPLATE

logger = logging.getLogger("template_editor")

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
    """Modo Básico — campos direto no formulário de editar dispositivo."""

    def __init__(self, parent):
        super().__init__(parent, text="Modelo de impressão", padding=6)
        self._blocos_customizados: list[dict] | None = None  # só o Modo Avançado mexe nisso

        self.mostrar_ie_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Mostrar Inscrição Estadual (IE)", variable=self.mostrar_ie_var).grid(
            row=0, column=0, columnspan=4, sticky="w"
        )

        ttk.Label(self, text="Título do cupom:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.cupom_titulo_entry = ttk.Entry(self, width=32)
        self.cupom_titulo_entry.grid(row=1, column=1, columnspan=3, sticky="we", padx=(4, 0), pady=(4, 0))

        ttk.Label(self, text="Mensagem padrão da empresa:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.mensagem_empresa_entry = ttk.Entry(self, width=42)
        self.mensagem_empresa_entry.grid(row=2, column=1, columnspan=3, sticky="we", padx=(4, 0), pady=(4, 0))

        ttk.Label(self, text="QR Code — módulo:").grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.qr_module_spin = ttk.Spinbox(self, from_=1, to=16, width=5)
        self.qr_module_spin.grid(row=3, column=1, sticky="w", padx=(4, 16), pady=(4, 0))
        ttk.Label(self, text="Correção de erro:").grid(row=3, column=2, sticky="w", pady=(4, 0))
        self.qr_ec_combo = ttk.Combobox(self, values=["L", "M", "Q", "H"], state="readonly", width=4)
        self.qr_ec_combo.grid(row=3, column=3, sticky="w", padx=(4, 0), pady=(4, 0))

        ttk.Button(self, text="Modo Avançado (cupom)...", command=self._open_advanced).grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )
        self.advanced_status = ttk.Label(self, text="", foreground="#a15c00")
        self.advanced_status.grid(row=5, column=0, columnspan=4, sticky="w")

    def load(self, template: dict) -> None:
        tpl = {**DEFAULT_TEMPLATE, **(template or {})}
        self.mostrar_ie_var.set(bool(tpl["mostrar_ie"]))
        self.cupom_titulo_entry.delete(0, tk.END)
        self.cupom_titulo_entry.insert(0, tpl["cupom_titulo"])
        self.mensagem_empresa_entry.delete(0, tk.END)
        self.mensagem_empresa_entry.insert(0, tpl["mensagem_empresa"])
        self.qr_module_spin.delete(0, tk.END)
        self.qr_module_spin.insert(0, str(tpl["qr_module_size"]))
        self.qr_ec_combo.set(tpl["qr_error_correction"])
        self._blocos_customizados = tpl.get("blocos_customizados") or None
        self._update_advanced_status()

    def read(self) -> dict:
        """Não inclui header_text/footer_text — esses continuam nos campos
        já existentes de Cabeçalho/Rodapé do formulário (DeviceDialog junta
        tudo antes de salvar)."""
        try:
            qr_module_size = int(self.qr_module_spin.get())
        except ValueError:
            qr_module_size = DEFAULT_TEMPLATE["qr_module_size"]
        qr_module_size = max(1, min(16, qr_module_size))

        return {
            "mostrar_ie": self.mostrar_ie_var.get(),
            "cupom_titulo": self.cupom_titulo_entry.get().strip() or DEFAULT_TEMPLATE["cupom_titulo"],
            "mensagem_empresa": self.mensagem_empresa_entry.get().strip(),
            "qr_module_size": qr_module_size,
            "qr_error_correction": self.qr_ec_combo.get() or "M",
            "blocos_customizados": self._blocos_customizados,
        }

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
