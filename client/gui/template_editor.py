"""
Status do modelo de impressão — só leitura. Editar layout aqui localmente
foi removido de propósito: decidir COMO o documento fiscal aparece agora é
sempre feito do lado do Simple ERP e chega pra este dispositivo por push
(job `set_template`, ver server/connector.py::send_template_update e
main.py::_dispatch_set_template/catalog.py::set_device_template) — o
Controller Machine só aplica e mostra aqui o que recebeu por último, pra dar
visibilidade a quem está olhando o dispositivo, sem abrir uma segunda porta
de edição que diverge do que o Simple ERP pensa que está configurado.
"""
from __future__ import annotations

from tkinter import ttk

from devices.printer_fiscal import DEFAULT_TEMPLATE


class TemplateStatusFrame(ttk.LabelFrame):
    """Mostra um resumo do modelo de impressão atualmente em cache — sem
    nenhum campo editável. Quem precisa mudar o layout muda no Simple ERP."""

    def __init__(self, parent):
        super().__init__(parent, text="Modelo de impressão (sincronizado pelo Simple ERP)", padding=6)
        self.summary_label = ttk.Label(self, text="", foreground="#555", justify="left", wraplength=380)
        self.summary_label.pack(anchor="w")

    def load(self, template: dict | None) -> None:
        if not template:
            self.summary_label.configure(
                text="Nenhum modelo recebido do Simple ERP ainda — usando o padrão de fábrica."
            )
            return

        tpl = {**DEFAULT_TEMPLATE, **template}
        partes = [f'Título do cupom: "{tpl["cupom_titulo"]}"']
        if tpl.get("header_text"):
            partes.append(f'Cabeçalho extra: "{tpl["header_text"]}"')
        if tpl.get("footer_text"):
            partes.append(f'Rodapé extra: "{tpl["footer_text"]}"')
        if tpl.get("mensagem_empresa"):
            partes.append(f'Mensagem padrão da empresa: "{tpl["mensagem_empresa"]}"')
        if tpl.get("blocos_customizados"):
            partes.append(f"Modo Avançado ativo no cupom ({len(tpl['blocos_customizados'])} bloco(s) customizado(s))")
        self.summary_label.configure(text="\n".join(partes))
