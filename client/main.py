# client/main.py
import socket
import threading
import json
import uuid
import queue
import platform
import logging
import time
import base64
import subprocess
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk, scrolledtext
import win32print  # Windows
import win32api   # Windows
try:
    import pystray
    from PIL import Image
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ClientGUI(tk.Toplevel):
    def __init__(self, parent, client, save_callback):
        super().__init__(parent)
        self.title("Cliente de Impressão Remota")
        self.client = client
        self.save_callback = save_callback
        self.geometry("600x400")

        # Configurações (removido auth_key e group)
        frame_config = tk.Frame(self)
        frame_config.pack(fill='x', padx=10, pady=10)

        tk.Label(frame_config, text="Host:").grid(row=0, column=0)
        self.host_entry = tk.Entry(frame_config)
        self.host_entry.insert(0, client.server_host)
        self.host_entry.grid(row=0, column=1)

        tk.Label(frame_config, text="Porta:").grid(row=1, column=0)
        self.port_entry = tk.Entry(frame_config)
        self.port_entry.insert(0, client.server_port)
        self.port_entry.grid(row=1, column=1)

        tk.Label(frame_config, text="Client ID:").grid(row=2, column=0)
        self.id_entry = tk.Entry(frame_config)
        self.id_entry.insert(0, client.client_id)
        self.id_entry.grid(row=2, column=1)

        tk.Label(frame_config, text="Impressora:").grid(row=3, column=0)
        self.printer_combo = ttk.Combobox(frame_config, values=self.list_printers())
        self.printer_combo.set(client.printer_name)
        self.printer_combo.grid(row=3, column=1)

        # Botões
        tk.Button(self, text="Salvar e Reconectar", command=self.save_and_reconnect).pack(pady=5)
        tk.Button(self, text="Conectar/Desconectar", command=self.toggle_connection).pack(pady=5)

        # Logs
        self.log_text = scrolledtext.ScrolledText(self, height=10)
        self.log_text.pack(fill='both', expand=True, padx=10, pady=10)

        # Redireciona logging para GUI
        class GUILogger(logging.Handler):
            def __init__(self, log_text):
                super().__init__()
                self.log_text = log_text

            def emit(self, record):
                if self.log_text:  # Verifica se existe
                    msg = self.format(record)
                    self.log_text.insert(tk.END, msg + '\n')
                    self.log_text.see(tk.END)

        logging.getLogger().addHandler(GUILogger(self.log_text))

    def list_printers(self):
        return [p[2] for p in win32print.EnumPrinters(2)]

    def save_and_reconnect(self):
        new_config = {
            'server_host': self.host_entry.get(),
            'server_port': int(self.port_entry.get()),
            'client_id': self.id_entry.get(),
            'printer_name': self.printer_combo.get()
        }
        self.save_callback(new_config)
        self.client.load_config(new_config)
        self.client.stop()  # Desconecta atual
        time.sleep(1)
        self.client.running = True
        self.client.retry_count = 0
        threading.Thread(target=self.client.connect_loop, daemon=True).start()

    def toggle_connection(self):
        if self.client.running:
            self.client.stop()
            messagebox.showinfo("Status", "Desconectado")
        else:
            self.client.running = True
            self.client.retry_count = 0
            threading.Thread(target=self.client.connect_loop, daemon=True).start()
            messagebox.showinfo("Status", "Conectando...")

class PrinterClient:
    def __init__(self, config):
        self.load_config(config)
        self.print_queue = queue.Queue()
        self.conn = None
        self.running = True
        self.os = platform.system()
        self.retry_count = 0
        self.max_retries = 30

        # Threads em background
        if self.is_config_valid():
            threading.Thread(target=self.connect_loop, daemon=True).start()
            threading.Thread(target=self.process_print_queue, daemon=True).start()
            threading.Thread(target=self.send_status_loop, daemon=True).start()

    def is_config_valid(self):
        return all([self.client_id, self.printer_name, self.server_host, self.server_port])

    def load_config(self, config):
        self.server_host = config.get('server_host', '127.0.0.1')
        self.server_port = config.get('server_port', 7689)
        self.client_id = config.get('client_id', '')
        self.printer_name = config.get('printer_name', '')

    def connect_loop(self):
        while self.running and self.retry_count < self.max_retries:
            try:
                self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.conn.connect((self.server_host, self.server_port))

                reg = {'type': 'register', 'client_id': self.client_id}
                self.conn.send(json.dumps(reg).encode('utf-8'))
                resp = json.loads(self.conn.recv(4096).decode('utf-8'))
                logging.info(f"Conectado: {resp}")

                if resp.get('status') == 'registered':
                    self.retry_count = 0
                    while self.running:
                        data = self.conn.recv(4096)
                        if not data:
                            break
                        msg = json.loads(data.decode('utf-8'))
                        if msg.get('type') == 'print':
                            self.print_queue.put(msg)
                else:
                    raise Exception(f"Erro de registro: {resp.get('message')}")

            except Exception as e:
                logging.error(f"Falha: {e}")
                if self.conn:
                    self.conn.close()
                    self.conn = None
                self.retry_count += 1
                if self.retry_count < self.max_retries:
                    logging.info(f"Tentativa {self.retry_count}/{self.max_retries}. Reconectando em 5s...")
                    time.sleep(5)
                else:
                    logging.error("Máximo de tentativas atingido. Parando.")
                    self.running = False

    def process_print_queue(self):
        while self.running:
            try:
                job = self.print_queue.get(timeout=1)
                data = base64.b64decode(job['data'])
                job_type = job.get('job_type', 'raw')

                if job_type == 'pdf':
                    self.print_pdf(data)
                else:
                    self.print_raw(data)

                if self.conn:
                    self.conn.send(json.dumps({'type': 'job_done'}).encode('utf-8'))
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Erro impressão: {e}")

    def print_raw(self, data):
        h = win32print.OpenPrinter(self.printer_name)
        win32print.StartDocPrinter(h, 1, ("Raw Print", None, "RAW"))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        win32print.ClosePrinter(h)

    def print_pdf(self, data):
        temp = 'C:\\temp_print.pdf'
        with open(temp, 'wb') as f:
            f.write(data)
        win32api.ShellExecute(0, "print", temp, None, ".", 0)
        time.sleep(2)
        os.remove(temp)

    def get_printer_status(self):
        try:
            h = win32print.OpenPrinter(self.printer_name)
            info = win32print.GetPrinter(h, 2)
            win32print.ClosePrinter(h)
            return {"ready": info['Status'] == 0, "code": info['Status']}
        except:
            return {"ready": False, "error": "Inacessível"}

    def send_status_loop(self):
        while self.running:
            time.sleep(60)
            if self.conn:
                try:
                    self.conn.send(json.dumps({'type': 'status_update', 'status': self.get_printer_status()}).encode('utf-8'))
                except:
                    pass

    def stop(self):
        self.running = False
        if self.conn:
            self.conn.close()

def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            'server_host': '127.0.0.1',
            'server_port': 7689,
            'client_id': '',
            'printer_name': win32print.GetDefaultPrinter() if platform.system() == 'Windows' else ''
        }

def save_config(config):
    with open('config.json', 'w') as f:
        json.dump(config, f)

if __name__ == '__main__':
    config = load_config()
    client = PrinterClient(config)

    root = tk.Tk()
    root.withdraw()  # Esconde principal

    gui = ClientGUI(root, client, save_config)

    if not client.is_config_valid():
        gui.deiconify()  # Mostra se inválida
    else:
        gui.withdraw()  # Esconde se válida, mas acessível via tray

    def open_gui(icon, item):
        gui.deiconify()

    def quit_app(icon, item):
        client.stop()
        icon.stop()
        root.quit()

    if HAS_TRAY:
        image = Image.new('RGB', (64, 64), color=(0, 200, 0))
        menu = pystray.Menu(
            pystray.MenuItem("Abrir Interface", open_gui),
            pystray.MenuItem("Sair", quit_app)
        )
        icon = pystray.Icon("PrinterClient", image, "Cliente Impressão", menu)
        logging.info("Rodando na bandeja")
        threading.Thread(target=icon.run, daemon=True).start()  # Tray em thread separada

    root.mainloop()  # GUI na main thread