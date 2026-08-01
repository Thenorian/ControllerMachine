"""
Janela de administração do Controller Machine — identidade/servidor,
cadastro de dispositivos e log, organizados em abas (estilo "Propriedades"
do Windows / OpenVPN GUI: simples, sem frescura). Abre a partir do ícone da
bandeja (Windows) ou pode rodar direto (Linux, sem tray — ver main.py).
"""
from __future__ import annotations

import logging
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from catalog import DeviceCatalog
from devices.scale import list_brands as list_scale_brands
from discovery import discover_os_printers
from gui.folder_prompt import FolderPromptService
from transport import ControllerTransport

TYPE_LABELS = {
    "printer_common": "Impressora",
    "printer_fiscal": "Impressora fiscal (DANFE)",
    "scale": "Balança",
}
TYPE_BY_LABEL = {v: k for k, v in TYPE_LABELS.items()}

CONNECTION_KINDS = {
    "printer_common": ["os_printer", "tcp"],
    "printer_fiscal": ["os_printer", "tcp", "pdf_folder"],
    "scale": ["tcp", "file", "serial"],
}
KIND_LABELS = {
    "os_printer": "Impressora instalada no SO",
    "tcp": "Rede (IP/porta)",
    "file": "Arquivo/pasta",
    "pdf_folder": "Salvar PDF numa pasta",
    "serial": "Porta serial",
}

MODE_LABELS = {
    "escpos": "ESC/POS (impressora térmica)",
    "raw": "Texto simples (RAW)",
}
MODE_BY_LABEL = {v: k for k, v in MODE_LABELS.items()}

# Marcas de balança conhecidas (formatters registrados em devices/scale) —
# nomes amigáveis pro combo; qualquer outro texto digitado é aceito também
# (o combo não é readonly), já que pode surgir marca nova ainda não coberta.
SCALE_BRAND_LABELS = {
    "toledo_mgv5_utf8": "Toledo Prix / MGV5 (UTF-8)",
    "toledo_mgv5_ibm860": "Toledo Prix / MGV5 (IBM860)",
    "ramuza_atena": "Ramuza Atena",
    "filizola": "Filizola",
}
SCALE_BRAND_BY_LABEL = {v: k for k, v in SCALE_BRAND_LABELS.items()}

# Só impressora de cupom (térmica, ESC/POS) precisa de modo/bobina — "salvar
# como PDF numa pasta" não imprime fisicamente, não faz sentido nenhum dos
# dois pra esse tipo de conexão.
KINDS_WITH_PRINT_SETTINGS = {"os_printer", "tcp"}

BAUD_RATES = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]


def _png_bytes(pil_image) -> bytes:
    import io
    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG")
    return buffer.getvalue()


class ControllerWindow(tk.Tk):
    def __init__(self, catalog: DeviceCatalog, transport: ControllerTransport):
        super().__init__()
        self.catalog = catalog
        self.transport = transport
        self.title("Controller Machine")
        self._set_icon()
        self.folder_prompt = FolderPromptService(self)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        general_tab = ttk.Frame(notebook)
        devices_tab = ttk.Frame(notebook)
        log_tab = ttk.Frame(notebook)
        notebook.add(general_tab, text="Geral")
        notebook.add(devices_tab, text="Dispositivos")
        notebook.add(log_tab, text="Log")

        self._build_general_tab(general_tab)
        self._build_devices_tab(devices_tab)
        self._build_log_tab(log_tab)
        self._refresh_devices()
        self._poll_status()

        # Tamanho fixo, como janela de Propriedades do Windows (Propriedades
        # de Usuário, de Pasta etc.) — não é redimensionável. Deixa o Tk
        # calcular o tamanho real que o conteúdo pede (em vez de forçar um
        # geometry() arbitrário, que corta botões/campos assim que a gente
        # adiciona mais coisa na tela) e trava nesse tamanho.
        self.update_idletasks()
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")
        self.resizable(False, False)

    def _set_icon(self) -> None:
        # iconbitmap cobre a barra de título; iconphoto é o que garante o
        # ícone certo na barra de tarefas/Alt+Tab do Windows — sem os dois,
        # às vezes o Windows usa o ícone genérico do interpretador Python.
        ico_path = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
        if ico_path.exists():
            try:
                self.iconbitmap(default=str(ico_path))
                self.iconbitmap(str(ico_path))
            except tk.TclError:
                pass

        try:
            from assets.generate_icon import build_icon_image
            self._icon_photo = tk.PhotoImage(master=self, data=_png_bytes(build_icon_image(scale=4)))
            self.iconphoto(True, self._icon_photo)
        except Exception:
            logging.getLogger("gui").exception("Falha ao aplicar iconphoto")

    # ------------------------------------------------------------------ #
    # Aba Geral
    # ------------------------------------------------------------------ #

    def _build_general_tab(self, parent: ttk.Frame) -> None:
        # Largura alvo próxima da de uma janela de Propriedades do Windows
        # (bem mais estreita que a versão anterior) — vem naturalmente de
        # encolher os campos (ID/secret não precisam mostrar o UUID inteiro
        # de uma vez) e mover os botões de ação pra linha de baixo, não do
        # lado — sem forçar width/propagate (isso cortava a altura).
        parent.configure(padding=10)

        # Rótulo numa coluna de largura fixa + campo do lado, igual formulário
        # de Propriedades do Windows — as duas caixas (Identidade/Servidor)
        # usam a mesma largura de coluna/campo pra alinhar entre si.
        LABEL_WIDTH = 12
        FIELD_WIDTH = 24

        identity = ttk.LabelFrame(parent, text="Identidade", padding=8)
        identity.pack(fill="x")

        ttk.Label(identity, text="Controller ID:", width=LABEL_WIDTH).grid(row=0, column=0, sticky="w", pady=2)
        id_entry = ttk.Entry(identity, width=FIELD_WIDTH)
        id_entry.insert(0, self.catalog.controller_id)
        id_entry.configure(state="readonly")
        id_entry.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(identity, text="Secret:", width=LABEL_WIDTH).grid(row=1, column=0, sticky="w", pady=2)
        secret_entry = ttk.Entry(identity, width=FIELD_WIDTH, show="*")
        secret_entry.insert(0, self.catalog.secret)
        secret_entry.configure(state="readonly")
        secret_entry.grid(row=1, column=1, sticky="w", pady=2)

        id_secret_buttons = ttk.Frame(identity)
        id_secret_buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(id_secret_buttons, text="Copiar ID",
                   command=lambda: self._copy_to_clipboard(self.catalog.controller_id)).pack(side="left")
        ttk.Button(id_secret_buttons, text="Copiar secret",
                   command=lambda: self._copy_to_clipboard(self.catalog.secret)).pack(side="left", padx=(4, 0))
        ttk.Button(id_secret_buttons, text="Mostrar",
                   command=lambda: self._toggle_secret(secret_entry)).pack(side="left", padx=(4, 0))

        server = ttk.LabelFrame(parent, text="Servidor", padding=8)
        server.pack(fill="x", pady=(8, 0))

        ttk.Label(server, text="Endereço:", width=LABEL_WIDTH).grid(row=0, column=0, sticky="w", pady=2)
        self.host_entry = ttk.Entry(server, width=FIELD_WIDTH)
        self.host_entry.insert(0, self.catalog.connector_host)
        self.host_entry.grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(server, text="Porta:", width=LABEL_WIDTH).grid(row=1, column=0, sticky="w", pady=2)
        self.port_entry = ttk.Entry(server, width=8)
        self.port_entry.insert(0, str(self.catalog.connector_port))
        self.port_entry.grid(row=1, column=1, sticky="w", pady=2)

        ttk.Button(server, text="Salvar e reconectar", command=self._save_and_reconnect).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        ttk.Label(server, text="Status:", width=LABEL_WIDTH).grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.status_label = ttk.Label(server, text="conectando...", foreground="#b8860b", wraplength=200)
        self.status_label.grid(row=3, column=1, sticky="w", pady=(8, 0))

    # ------------------------------------------------------------------ #
    # Aba Dispositivos
    # ------------------------------------------------------------------ #

    def _build_devices_tab(self, parent: ttk.Frame) -> None:
        parent.configure(padding=10)

        # Detalhe de conexão não entra na tabela (empurraria a largura da
        # janela) — quem quiser ver IP/caminho/etc. abre Editar.
        columns = ("label", "type", "brand")
        self.tree = ttk.Treeview(parent, columns=columns, show="headings", height=10)
        headings = {"label": "Nome", "type": "Tipo", "brand": "Marca"}
        widths = {"label": 95, "type": 95, "brand": 70}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col])
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self._edit_selected())

        buttons = ttk.Frame(parent)
        buttons.pack(side="right", fill="y", padx=(6, 0))
        ttk.Button(buttons, text="Adicionar", width=10, command=self._add_device).pack(fill="x", pady=2)
        ttk.Button(buttons, text="Editar", width=10, command=self._edit_selected).pack(fill="x", pady=2)
        ttk.Button(buttons, text="Remover", width=10, command=self._remove_selected).pack(fill="x", pady=2)

    # ------------------------------------------------------------------ #
    # Aba Log
    # ------------------------------------------------------------------ #

    def _build_log_tab(self, parent: ttk.Frame) -> None:
        from tkinter import scrolledtext

        parent.configure(padding=10)
        self.log_text = scrolledtext.ScrolledText(parent, height=14)
        self.log_text.pack(fill="both", expand=True)

        # Logs chegam de threads em segundo plano (ex.: ControllerTransport,
        # que roda numa thread própria) — nunca é seguro mexer em widget Tk
        # fora da thread principal, então o handler só enfileira (thread-safe)
        # e quem realmente insere no widget é o polling abaixo, na main loop.
        self._log_queue: "queue.Queue[str]" = queue.Queue()

        class GuiLogHandler(logging.Handler):
            def __init__(self, log_queue):
                super().__init__()
                self.log_queue = log_queue

            def emit(self, record):
                self.log_queue.put(self.format(record))

        logging.getLogger().addHandler(GuiLogHandler(self._log_queue))
        self._poll_log_queue()

    def _poll_log_queue(self) -> None:
        while True:
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
        self.after(200, self._poll_log_queue)

    # ------------------------------------------------------------------ #

    def _refresh_devices(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for device in self.catalog.list_devices():
            self.tree.insert("", "end", iid=device["device_id"], values=(
                device["label"],
                TYPE_LABELS.get(device["type"], device["type"]),
                device["brand"],
            ))

    def _poll_status(self) -> None:
        if self.transport.connected:
            self.status_label.configure(text="conectado", foreground="#1a7f37")
        elif self.transport.server_reachable:
            motivo = self.transport.last_error or "aguardando registro"
            self.status_label.configure(text=f"servidor encontrado — {motivo}", foreground="#b8860b")
        else:
            self.status_label.configure(text="servidor não encontrado — tentando reconectar", foreground="#c0392b")
        self.after(3000, self._poll_status)

    def _copy_to_clipboard(self, value: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)

    @staticmethod
    def _toggle_secret(entry: tk.Entry) -> None:
        entry.configure(show="" if entry.cget("show") == "*" else "*")

    def _save_and_reconnect(self) -> None:
        host = self.host_entry.get().strip()
        try:
            port = int(self.port_entry.get())
        except ValueError:
            messagebox.showwarning("Porta inválida", "A porta precisa ser um número.")
            return
        if not host:
            messagebox.showwarning("Servidor obrigatório", "Preencha o endereço do servidor.")
            return

        self.catalog.set_connector(host, port)
        self.transport.point_to(host, port)
        self.status_label.configure(text="reconectando...", foreground="#b8860b")

    # ------------------------------------------------------------------ #

    def _add_device(self) -> None:
        dialog = DeviceDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.catalog.add_device(**dialog.result)
            self._after_catalog_change()

    def _edit_selected(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            return
        device = self.catalog.get_device(device_id)
        dialog = DeviceDialog(self, device=device)
        self.wait_window(dialog)
        if dialog.result:
            self.catalog.update_device(device_id, **dialog.result)
            self._after_catalog_change()

    def _remove_selected(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            return
        if messagebox.askyesno("Confirmar", "Remover este dispositivo do catálogo local?"):
            self.catalog.remove_device(device_id)
            self._after_catalog_change()

    def _selected_device_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _after_catalog_change(self) -> None:
        self._refresh_devices()
        self.transport.notify_catalog_changed()


def _make_dialog_visible(top: tk.Toplevel) -> None:
    """Garante que o Toplevel apareça na frente e com foco antes de travar
    o grab — chamar grab_set() antes da janela estar de fato visível pode
    tanto estourar "grab failed: window not viewable" quanto (silenciosamente,
    dependendo do gerenciador de janelas) deixar o popup aberto atrás da
    janela principal, dando a impressão de que o botão não fez nada."""
    top.wait_visibility()
    top.grab_set()
    top.lift()
    top.focus_force()


class DeviceDialog(tk.Toplevel):
    """Cadastro e edição de dispositivo — o mesmo formulário serve pros dois
    casos (`device=None` cadastra, `device={...}` edita esse device). Os
    campos disponíveis mudam de acordo com o Tipo e a Conexão escolhidos."""

    def __init__(self, parent, device: dict | None = None):
        super().__init__(parent)
        self.editing = device is not None
        self.result = None
        self.title("Editar dispositivo" if self.editing else "Adicionar dispositivo")
        self.resizable(False, False)

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)

        row = 0
        ttk.Label(body, text="Nome:").grid(row=row, column=0, sticky="w", pady=2)
        self.label_entry = ttk.Entry(body, width=32)
        self.label_entry.grid(row=row, column=1, columnspan=2, sticky="w", pady=2)
        row += 1

        ttk.Label(body, text="Tipo:").grid(row=row, column=0, sticky="w", pady=2)
        self.type_combo = ttk.Combobox(body, values=list(TYPE_LABELS.values()), state="readonly", width=29)
        self.type_combo.grid(row=row, column=1, columnspan=2, sticky="w", pady=2)
        self.type_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_type_changed())
        row += 1

        ttk.Label(body, text="Marca:").grid(row=row, column=0, sticky="w", pady=2)
        self.brand_combo = ttk.Combobox(body, width=29)
        self.brand_combo.grid(row=row, column=1, columnspan=2, sticky="w", pady=2)
        row += 1

        ttk.Label(body, text="Conexão:").grid(row=row, column=0, sticky="w", pady=2)
        self.kind_combo = ttk.Combobox(body, state="readonly", width=29)
        self.kind_combo.grid(row=row, column=1, columnspan=2, sticky="w", pady=2)
        self.kind_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_kind_changed())
        row += 1

        self.kind_container = ttk.Frame(body)
        self.kind_container.grid(row=row, column=0, columnspan=3, sticky="we", pady=(4, 0))
        row += 1

        self.settings_frame = ttk.LabelFrame(body, text="Impressão (cupom térmico)", padding=6)
        self.settings_frame.grid(row=row, column=0, columnspan=3, sticky="we", pady=(8, 0))
        ttk.Label(self.settings_frame, text="Modo:").grid(row=0, column=0, sticky="w")
        self.mode_combo = ttk.Combobox(self.settings_frame, values=list(MODE_LABELS.values()),
                                        state="readonly", width=24)
        self.mode_combo.grid(row=0, column=1, sticky="w", padx=(4, 16))
        ttk.Label(self.settings_frame, text="Bobina:").grid(row=0, column=2, sticky="w")
        self.paper_combo = ttk.Combobox(self.settings_frame, values=["40mm", "80mm"], state="readonly", width=8)
        self.paper_combo.grid(row=0, column=3, sticky="w", padx=(4, 0))
        row += 1

        self._build_kind_frames()

        buttons = ttk.Frame(body)
        buttons.grid(row=row, column=0, columnspan=3, pady=(12, 0))
        ttk.Button(buttons, text="Salvar" if self.editing else "Adicionar", command=self._confirm).pack(side="left")
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="left", padx=(6, 0))

        self._load(device)
        self.transient(parent)
        _make_dialog_visible(self)

    # ---- sub-formulários por kind de conexão ----

    def _build_kind_frames(self) -> None:
        self.kind_frames: dict[str, ttk.Frame] = {}
        self._visible_kind_frame: ttk.Frame | None = None

        f = ttk.Frame(self.kind_container)
        ttk.Label(f, text="Impressora:").grid(row=0, column=0, sticky="w")
        self.os_printer_combo = ttk.Combobox(f, values=discover_os_printers(), width=30)
        self.os_printer_combo.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.kind_frames["os_printer"] = f

        f = ttk.Frame(self.kind_container)
        ttk.Label(f, text="IP:").grid(row=0, column=0, sticky="w")
        self.tcp_host_entry = ttk.Entry(f, width=20)
        self.tcp_host_entry.grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(f, text="Porta:").grid(row=0, column=2, sticky="w")
        self.tcp_port_entry = ttk.Entry(f, width=8)
        self.tcp_port_entry.grid(row=0, column=3, sticky="w", padx=(4, 0))
        self.kind_frames["tcp"] = f

        f = ttk.Frame(self.kind_container)
        ttk.Label(f, text="Arquivo:").grid(row=0, column=0, sticky="w")
        self.path_entry = ttk.Entry(f, width=28)
        self.path_entry.grid(row=0, column=1, sticky="w", padx=(4, 4))
        ttk.Button(f, text="...", width=3, command=self._browse_file_path).grid(row=0, column=2)
        self.kind_frames["file"] = f

        f = ttk.Frame(self.kind_container)
        ttk.Label(f, text="Pasta:").grid(row=0, column=0, sticky="w")
        self.pdf_folder_entry = ttk.Entry(f, width=28)
        self.pdf_folder_entry.grid(row=0, column=1, sticky="w", padx=(4, 4))
        self.pdf_folder_browse_btn = ttk.Button(f, text="...", width=3, command=self._browse_folder_path)
        self.pdf_folder_browse_btn.grid(row=0, column=2)
        self.ask_each_time_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f, text="Perguntar a pasta a cada impressão (sem pasta fixa)",
            variable=self.ask_each_time_var, command=self._on_ask_each_time_changed,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.kind_frames["pdf_folder"] = f

        f = ttk.Frame(self.kind_container)
        ttk.Label(f, text="Porta serial:").grid(row=0, column=0, sticky="w")
        self.serial_port_entry = ttk.Entry(f, width=14)
        self.serial_port_entry.grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(f, text="Baud:").grid(row=0, column=2, sticky="w")
        self.baud_combo = ttk.Combobox(f, values=BAUD_RATES, state="readonly", width=8)
        self.baud_combo.grid(row=0, column=3, sticky="w", padx=(4, 0))
        self.kind_frames["serial"] = f

    def _show_kind_frame(self, kind: str) -> None:
        if self._visible_kind_frame is not None:
            self._visible_kind_frame.grid_forget()
        frame = self.kind_frames[kind]
        frame.grid(row=0, column=0, sticky="w")
        self._visible_kind_frame = frame

    def _current_type(self) -> str:
        return TYPE_BY_LABEL[self.type_combo.get()]

    def _on_type_changed(self, *, preserve_kind: str | None = None) -> None:
        type_ = self._current_type()
        kinds = CONNECTION_KINDS[type_]
        self.kind_combo.configure(values=[KIND_LABELS[k] for k in kinds])
        self._kind_by_label = {KIND_LABELS[k]: k for k in kinds}

        if preserve_kind and preserve_kind in kinds:
            self.kind_combo.set(KIND_LABELS[preserve_kind])
        else:
            self.kind_combo.current(0)
        self._on_kind_changed()

        if type_ == "scale":
            self.brand_combo.configure(values=[SCALE_BRAND_LABELS.get(b, b) for b in list_scale_brands()])
        else:
            self.brand_combo.configure(values=["generic"])

    def _on_kind_changed(self) -> None:
        kind = self._kind_by_label.get(self.kind_combo.get())
        if kind:
            self._show_kind_frame(kind)

        type_ = self._current_type()
        show_settings = type_ in ("printer_common", "printer_fiscal") and kind in KINDS_WITH_PRINT_SETTINGS
        if show_settings:
            self.settings_frame.grid()
        else:
            self.settings_frame.grid_remove()

    def _browse_file_path(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, title="Arquivo de exportação")
        if path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, path)

    def _browse_folder_path(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Pasta de destino")
        if path:
            self.pdf_folder_entry.delete(0, tk.END)
            self.pdf_folder_entry.insert(0, path)

    def _on_ask_each_time_changed(self) -> None:
        state = "disabled" if self.ask_each_time_var.get() else "normal"
        self.pdf_folder_entry.configure(state=state)
        self.pdf_folder_browse_btn.configure(state=state)

    # ---- carregar valores existentes (modo edição) ----

    def _load(self, device: dict | None) -> None:
        self.mode_combo.set(MODE_LABELS["escpos"])
        self.paper_combo.set("80mm")
        self.baud_combo.set("9600")

        if device is None:
            self.type_combo.current(0)
            self._on_type_changed()
            return

        self.label_entry.insert(0, device["label"])
        self.type_combo.set(TYPE_LABELS.get(device["type"], device["type"]))
        connection = device["connection"]
        self._on_type_changed(preserve_kind=connection.get("kind"))

        if device["type"] == "scale":
            self.brand_combo.set(SCALE_BRAND_LABELS.get(device["brand"], device["brand"]))
        else:
            self.brand_combo.set(device["brand"])

        settings = device.get("settings") or {}
        if settings.get("mode"):
            self.mode_combo.set(MODE_LABELS.get(settings["mode"], settings["mode"]))
        if settings.get("paper_width_mm"):
            self.paper_combo.set(f"{settings['paper_width_mm']}mm")

        kind = connection.get("kind")
        if kind == "os_printer":
            self.os_printer_combo.set(connection.get("os_name", ""))
        elif kind == "tcp":
            self.tcp_host_entry.insert(0, connection.get("host", ""))
            self.tcp_port_entry.insert(0, str(connection.get("port", "")))
        elif kind == "file":
            self.path_entry.insert(0, connection.get("path", ""))
        elif kind == "pdf_folder":
            if connection.get("ask_each_time"):
                self.ask_each_time_var.set(True)
                self._on_ask_each_time_changed()
            self.pdf_folder_entry.insert(0, connection.get("path", ""))
        elif kind == "serial":
            self.serial_port_entry.insert(0, connection.get("serial_port", ""))
            self.baud_combo.set(str(connection.get("baudrate", 9600)))

    # ---- confirmar ----

    def _confirm(self) -> None:
        label = self.label_entry.get().strip()
        if not label:
            messagebox.showwarning("Campo obrigatório", "Preencha o nome do dispositivo.")
            return

        type_ = self._current_type()
        kind = self._kind_by_label.get(self.kind_combo.get())

        connection = self._read_connection(kind)
        if connection is None:
            return  # já mostrou o aviso

        settings = {}
        if type_ in ("printer_common", "printer_fiscal") and kind in KINDS_WITH_PRINT_SETTINGS:
            settings["mode"] = MODE_BY_LABEL.get(self.mode_combo.get(), "escpos")
            paper = self.paper_combo.get()
            if not paper:
                messagebox.showwarning("Campo obrigatório", "Selecione a largura da bobina.")
                return
            settings["paper_width_mm"] = int(paper.replace("mm", ""))

        brand = self.brand_combo.get().strip() or "generic"
        if type_ == "scale":
            brand = SCALE_BRAND_BY_LABEL.get(brand, brand)

        self.result = {
            "label": label,
            "type_": type_,
            "brand": brand,
            "connection": connection,
            "settings": settings,
        }
        self.destroy()

    def _read_connection(self, kind: str) -> dict | None:
        if kind == "os_printer":
            os_name = self.os_printer_combo.get().strip()
            if not os_name:
                messagebox.showwarning("Campo obrigatório", "Escolha a impressora instalada.")
                return None
            return {"kind": "os_printer", "os_name": os_name}

        if kind == "tcp":
            host = self.tcp_host_entry.get().strip()
            if not host:
                messagebox.showwarning("Campo obrigatório", "Preencha o IP.")
                return None
            try:
                port = int(self.tcp_port_entry.get())
            except ValueError:
                messagebox.showwarning("Porta inválida", "A porta precisa ser um número.")
                return None
            return {"kind": "tcp", "host": host, "port": port}

        if kind == "file":
            path = self.path_entry.get().strip()
            if not path:
                messagebox.showwarning("Campo obrigatório", "Preencha o caminho do arquivo.")
                return None
            return {"kind": "file", "path": path}

        if kind == "pdf_folder":
            ask_each_time = self.ask_each_time_var.get()
            path = self.pdf_folder_entry.get().strip()
            if not ask_each_time and not path:
                messagebox.showwarning(
                    "Campo obrigatório",
                    "Preencha a pasta de destino ou marque \"Perguntar a pasta a cada impressão\".",
                )
                return None
            return {"kind": "pdf_folder", "path": path, "ask_each_time": ask_each_time}

        if kind == "serial":
            serial_port = self.serial_port_entry.get().strip()
            if not serial_port:
                messagebox.showwarning("Campo obrigatório", "Preencha a porta serial.")
                return None
            return {"kind": "serial", "serial_port": serial_port, "baudrate": int(self.baud_combo.get() or 9600)}

        raise ValueError(f"kind desconhecido: {kind!r}")
