"""
Pergunta ao operador em qual pasta salvar um PDF, de forma segura mesmo
sendo chamado a partir de uma thread de fundo (ex.: a thread do
ControllerTransport, que é quem recebe o job e chama handle_job).

Tkinter só permite abrir diálogos/mexer em widgets na thread principal —
por isso `ask_folder` (chamado de qualquer thread) só enfileira o pedido e
bloqueia esperando a resposta; quem realmente chama `filedialog.askdirectory`
é o polling rodando na main loop (mesmo padrão do log thread-safe em
gui/window.py).
"""
from __future__ import annotations

import queue
from tkinter import filedialog


class FolderPromptService:
    def __init__(self, window):
        self.window = window
        self._requests: "queue.Queue[tuple[queue.Queue, str]]" = queue.Queue()
        self._poll()

    def _poll(self) -> None:
        try:
            while True:
                response_queue, title = self._requests.get_nowait()
                path = filedialog.askdirectory(parent=self.window, title=title) or None
                response_queue.put(path)
        except queue.Empty:
            pass
        self.window.after(200, self._poll)

    def ask_folder(self, title: str = "Selecione a pasta para salvar o PDF", timeout: float = 120) -> str | None:
        """Bloqueia a thread chamadora até o operador escolher (ou fechar) o
        diálogo — ou até `timeout` segundos se ninguém responder (ex.: janela
        fechada, operador ausente), pra nunca travar a thread do transport
        pra sempre."""
        response_queue: "queue.Queue[str | None]" = queue.Queue(maxsize=1)
        self._requests.put((response_queue, title))
        try:
            return response_queue.get(timeout=timeout)
        except queue.Empty:
            return None
