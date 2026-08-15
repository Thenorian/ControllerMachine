"""
Instalador Windows do Controller Machine.

De propósito minúsculo e feito só com Tkinter (stdlib) + pywin32 (já é
dependência do próprio Controller Machine) — a única serventia dele é copiar
o ControllerMachine.exe já compilado (embutido aqui dentro como dado do
PyInstaller, ver windows_installer.spec) pro destino escolhido e configurar
o que for marcado. Depois disso ele é descartável.

Builda DEPOIS do ControllerMachine.exe (ver .github/workflows/
build-windows-exe.yml) — o .spec deste instalador embute o .exe já pronto.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

APP_NAME = "Controller Machine"
DEFAULT_INSTALL_DIR = r"C:\thenorian\controller"


def bundled_path(*parts: str) -> Path:
    """Dados embutidos pelo PyInstaller (--onefile extrai pra uma pasta
    temporária em tempo de execução, sys._MEIPASS aponta pra ela)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def schedule_self_delete(installer_exe: Path) -> None:
    """Um .exe rodando não consegue apagar a si mesmo no Windows (arquivo
    fica travado) — dispara um .bat separado que espera o processo soltar o
    arquivo (tentando apagar em loop) e depois se apaga também."""
    bat_path = installer_exe.with_suffix(".selfdelete.bat")
    bat_content = (
        "@echo off\r\n"
        ":loop\r\n"
        f'del "{installer_exe}" >nul 2>&1\r\n'
        f'if exist "{installer_exe}" goto loop\r\n'
        f'del "{bat_path}"\r\n'
    )
    bat_path.write_text(bat_content, encoding="utf-8")
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )


class InstallerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Instalar {APP_NAME}")
        self.resizable(False, False)
        self.geometry("560x360")
        try:
            self.iconbitmap(str(bundled_path("payload", "assets", "icon.ico")))
        except Exception:
            pass

        self.install_dir_var = tk.StringVar(value=DEFAULT_INSTALL_DIR)
        self.autostart_var = tk.BooleanVar(value=True)
        self.delete_installer_var = tk.BooleanVar(value=True)
        self._installed_exe: Path | None = None

        # Banner grande na lateral esquerda (mesmo espírito do instalador do
        # Python) — usa o ícone do app, PNG lido direto pelo Tk 8.6+, sem
        # precisar de Pillow só pra isso (instalador tem que ficar pequeno).
        banner = tk.Frame(self, width=180, height=360, bg="#1a1a2e")
        banner.pack(side="left", fill="y")
        banner.pack_propagate(False)
        try:
            self._banner_image = tk.PhotoImage(file=str(bundled_path("icon.png")))
            if self._banner_image.width() > 140:
                factor = max(1, self._banner_image.width() // 140)
                self._banner_image = self._banner_image.subsample(factor, factor)
            tk.Label(banner, image=self._banner_image, bg="#1a1a2e").pack(expand=True)
        except Exception:
            tk.Label(banner, text=APP_NAME, fg="white", bg="#1a1a2e",
                      wraplength=150, font=("Segoe UI", 14, "bold")).pack(expand=True)

        self.content = tk.Frame(self, padx=20, pady=20)
        self.content.pack(side="left", fill="both", expand=True)

        self._show_welcome_screen()

    def _clear_content(self) -> None:
        for widget in self.content.winfo_children():
            widget.destroy()

    def _show_welcome_screen(self) -> None:
        self._clear_content()
        c = self.content

        tk.Label(c, text=f"Bem-vindo ao instalador do {APP_NAME}",
                 font=("Segoe UI", 12, "bold"), wraplength=340, justify="left").pack(anchor="w")
        tk.Label(c, text="Escolha a pasta de instalação e clique em Instalar.",
                 wraplength=340, justify="left").pack(anchor="w", pady=(4, 16))

        tk.Label(c, text="Pasta de instalação:").pack(anchor="w")
        path_row = tk.Frame(c)
        path_row.pack(fill="x", pady=(2, 16))
        tk.Entry(path_row, textvariable=self.install_dir_var, width=42).pack(side="left")
        tk.Button(path_row, text="...", command=self._browse_dir).pack(side="left", padx=(6, 0))

        tk.Checkbutton(c, text="Iniciar automaticamente com o Windows",
                        variable=self.autostart_var).pack(anchor="w")

        tk.Frame(c).pack(expand=True, fill="both")  # empurra os botões pro rodapé

        buttons = tk.Frame(c)
        buttons.pack(anchor="e", pady=(16, 0))
        tk.Button(buttons, text="Cancelar", command=self.destroy, width=12).pack(side="left", padx=(0, 8))
        tk.Button(buttons, text="Instalar", command=self._do_install, width=12,
                   default="active").pack(side="left")

    def _browse_dir(self) -> None:
        chosen = filedialog.askdirectory(title="Escolher pasta de instalação")
        if chosen:
            self.install_dir_var.set(str(Path(chosen) / "thenorian" / "controller"))

    def _do_install(self) -> None:
        install_dir = Path(self.install_dir_var.get().strip())
        if not install_dir:
            messagebox.showerror(APP_NAME, "Escolha uma pasta de instalação.")
            return

        try:
            install_dir.mkdir(parents=True, exist_ok=True)
            (install_dir / "logs").mkdir(exist_ok=True)

            target_exe = install_dir / "ControllerMachine.exe"
            shutil.copyfile(bundled_path("payload", "ControllerMachine.exe"), target_exe)

            if self.autostart_var.get():
                # Reaproveita a lógica que já existe no próprio app
                # (gui/tray.py::install_windows_autostart) em vez de duplicar
                # criação de atalho aqui — só chama o .exe recém-copiado com
                # a flag que já faz exatamente isso e sai sem abrir janela.
                subprocess.run([str(target_exe), "--install-autostart"], check=True)

            self._installed_exe = target_exe
        except PermissionError:
            messagebox.showerror(
                APP_NAME,
                "Sem permissão para instalar nessa pasta, ou o Controller Machine "
                "já está em execução (feche-o e tente de novo).",
            )
            return
        except Exception as err:
            messagebox.showerror(APP_NAME, f"Falha na instalação: {err}")
            return

        self._show_finish_screen()

    def _show_finish_screen(self) -> None:
        self._clear_content()
        c = self.content

        tk.Label(c, text="Instalação concluída", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(
            c,
            text=f"{APP_NAME} foi instalado em:\n{self._installed_exe}",
            wraplength=340, justify="left",
        ).pack(anchor="w", pady=(4, 16))

        tk.Checkbutton(c, text="Excluir instalador", variable=self.delete_installer_var).pack(anchor="w")

        tk.Frame(c).pack(expand=True, fill="both")

        buttons = tk.Frame(c)
        buttons.pack(anchor="e", pady=(16, 0))
        tk.Button(buttons, text="Concluir", command=self._finish, width=12,
                   default="active").pack(side="left")

    def _finish(self) -> None:
        if self.delete_installer_var.get() and getattr(sys, "frozen", False):
            schedule_self_delete(Path(sys.executable))
        self.destroy()


def main() -> None:
    InstallerApp().mainloop()


if __name__ == "__main__":
    main()
