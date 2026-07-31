"""
Janela de administração do Controller Machine — cadastro de dispositivos,
status da conexão e log. Abre a partir do ícone da bandeja (Windows) ou pode
rodar direto (Linux, sem tray — ver main.py).
"""
from __future__ import annotations

import logging
import queue
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from catalog import DeviceCatalog
from discovery import discover_os_printers
from transport import ControllerTransport


class ControllerWindow(tk.Tk):
    def __init__(self, catalog: DeviceCatalog, transport: ControllerTransport):
        super().__init__()
        self.catalog = catalog
        self.transport = transport

        self.title("Controller Machine")
        self.geometry("640x420")

        self._build_status_frame()
        self._build_device_list()
        self._build_log_area()
        self._refresh_devices()
        self._poll_status()

    # ------------------------------------------------------------------ #

    def _build_status_frame(self) -> None:
        frame = tk.Frame(self)
        frame.pack(fill="x", padx=10, pady=10)

        tk.Label(frame, text="Controller ID:").grid(row=0, column=0, sticky="w")
        id_entry = tk.Entry(frame, width=40)
        id_entry.grid(row=0, column=1, sticky="w", columnspan=3)
        id_entry.insert(0, self.catalog.controller_id)
        id_entry.configure(state="readonly")
        tk.Button(frame, text="Copiar", command=lambda: self._copy_to_clipboard(self.catalog.controller_id)).grid(
            row=0, column=4, sticky="w", padx=(10, 0)
        )

        tk.Label(frame, text="Secret:").grid(row=1, column=0, sticky="w")
        secret_entry = tk.Entry(frame, width=40, show="*")
        secret_entry.grid(row=1, column=1, sticky="w", columnspan=3)
        secret_entry.insert(0, self.catalog.secret)
        secret_entry.configure(state="readonly")
        tk.Button(frame, text="Copiar", command=lambda: self._copy_to_clipboard(self.catalog.secret)).grid(
            row=1, column=4, sticky="w", padx=(10, 0)
        )
        tk.Button(frame, text="Mostrar", command=lambda: self._toggle_secret(secret_entry)).grid(
            row=1, column=5, sticky="w", padx=(5, 0)
        )

        tk.Label(frame, text="Servidor:").grid(row=2, column=0, sticky="w")
        self.host_entry = tk.Entry(frame, width=24)
        self.host_entry.insert(0, self.catalog.connector_host)
        self.host_entry.grid(row=2, column=1, sticky="w")

        tk.Label(frame, text="Porta:").grid(row=2, column=2, sticky="w")
        self.port_entry = tk.Entry(frame, width=8)
        self.port_entry.insert(0, str(self.catalog.connector_port))
        self.port_entry.grid(row=2, column=3, sticky="w")

        tk.Button(frame, text="Salvar e reconectar", command=self._save_and_reconnect).grid(
            row=2, column=4, sticky="w", padx=(10, 0)
        )

        tk.Label(frame, text="Status:").grid(row=3, column=0, sticky="w")
        self.status_label = tk.Label(frame, text="conectando...", fg="orange")
        self.status_label.grid(row=3, column=1, sticky="w")

    def _build_device_list(self) -> None:
        frame = tk.LabelFrame(self, text="Dispositivos cadastrados")
        frame.pack(fill="both", expand=True, padx=10, pady=5)

        columns = ("label", "type", "brand")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for col, title in zip(columns, ("Label", "Tipo", "Marca")):
            self.tree.heading(col, text=title)
        self.tree.pack(fill="both", expand=True, side="left", padx=5, pady=5)

        buttons = tk.Frame(frame)
        buttons.pack(side="right", fill="y", padx=5)
        tk.Button(buttons, text="Adicionar impressora do SO", command=self._add_os_printer).pack(fill="x", pady=2)
        tk.Button(buttons, text="Adicionar dispositivo de rede", command=self._add_network_device).pack(fill="x", pady=2)
        tk.Button(buttons, text="Renomear", command=self._rename_selected).pack(fill="x", pady=2)
        tk.Button(buttons, text="Remover", command=self._remove_selected).pack(fill="x", pady=2)

    def _build_log_area(self) -> None:
        from tkinter import scrolledtext

        self.log_text = scrolledtext.ScrolledText(self, height=8)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

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
            self.tree.insert("", "end", iid=device["device_id"],
                              values=(device["label"], device["type"], device["brand"]))

    def _poll_status(self) -> None:
        if self.transport.connected:
            self.status_label.configure(text="conectado", fg="green")
        else:
            self.status_label.configure(text="desconectado — tentando reconectar", fg="red")
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
        self.status_label.configure(text="reconectando...", fg="orange")

    # ------------------------------------------------------------------ #

    def _add_os_printer(self) -> None:
        printers = discover_os_printers()
        if not printers:
            messagebox.showinfo("Nenhuma impressora encontrada",
                                 "Não achei nenhuma impressora instalada no sistema.")
            return

        chosen = _choose_from_list(self, "Impressoras instaladas", printers)
        if not chosen:
            return
        label = simpledialog.askstring("Label", "Nome de exibição:", initialvalue=chosen)
        if not label:
            return

        self.catalog.add_device(
            label=label, type_="printer_common", brand="generic",
            connection={"kind": "os_printer", "os_name": chosen},
        )
        self._after_catalog_change()

    def _add_network_device(self) -> None:
        dialog = NetworkDeviceDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.catalog.add_device(**dialog.result)
            self._after_catalog_change()

    def _rename_selected(self) -> None:
        device_id = self._selected_device_id()
        if not device_id:
            return
        new_label = simpledialog.askstring("Renomear", "Novo nome:")
        if new_label:
            self.catalog.rename_device(device_id, new_label)
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


def _choose_from_list(parent, title: str, options: list[str]) -> str | None:
    top = tk.Toplevel(parent)
    top.title(title)
    listbox = tk.Listbox(top, width=50, height=10)
    for option in options:
        listbox.insert(tk.END, option)
    listbox.pack(padx=10, pady=10)

    result = {"value": None}

    def confirm():
        selection = listbox.curselection()
        if selection:
            result["value"] = listbox.get(selection[0])
        top.destroy()

    tk.Button(top, text="Selecionar", command=confirm).pack(pady=(0, 10))
    top.grab_set()
    parent.wait_window(top)
    return result["value"]


class NetworkDeviceDialog(tk.Toplevel):
    """Cadastro manual — usado pra balança e impressora de rede que não
    aparecem na lista de impressoras instaladas no SO."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Adicionar dispositivo de rede")
        self.result = None

        tk.Label(self, text="Label:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.label_entry = tk.Entry(self)
        self.label_entry.grid(row=0, column=1, padx=5, pady=2)

        tk.Label(self, text="Tipo:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.type_combo = ttk.Combobox(self, values=["printer_common", "printer_fiscal", "scale"], state="readonly")
        self.type_combo.current(0)
        self.type_combo.grid(row=1, column=1, padx=5, pady=2)

        tk.Label(self, text="Marca:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.brand_entry = tk.Entry(self)
        self.brand_entry.insert(0, "generic")
        self.brand_entry.grid(row=2, column=1, padx=5, pady=2)

        tk.Label(self, text="IP:").grid(row=3, column=0, sticky="w", padx=5, pady=2)
        self.host_entry = tk.Entry(self)
        self.host_entry.grid(row=3, column=1, padx=5, pady=2)

        tk.Label(self, text="Porta:").grid(row=4, column=0, sticky="w", padx=5, pady=2)
        self.port_entry = tk.Entry(self)
        self.port_entry.insert(0, "9100")
        self.port_entry.grid(row=4, column=1, padx=5, pady=2)

        tk.Button(self, text="Adicionar", command=self._confirm).grid(row=5, column=0, columnspan=2, pady=10)

    def _confirm(self) -> None:
        label = self.label_entry.get().strip()
        host = self.host_entry.get().strip()
        if not label or not host:
            messagebox.showwarning("Campos obrigatórios", "Preencha ao menos Label e IP.")
            return
        try:
            port = int(self.port_entry.get())
        except ValueError:
            messagebox.showwarning("Porta inválida", "A porta precisa ser um número.")
            return

        self.result = {
            "label": label,
            "type_": self.type_combo.get(),
            "brand": self.brand_entry.get().strip() or "generic",
            "connection": {"kind": "tcp", "host": host, "port": port},
        }
        self.destroy()
