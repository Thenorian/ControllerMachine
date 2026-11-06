#!/bin/bash
# Instalador Linux do Controller Machine — roda a partir do .tar.gz gerado
# por installer/build_linux_package.py (contém este script + a pasta app/
# com o código do client). Cria a instalação em ~/.thenorian/controller,
# um venv isolado com as dependências, registra como serviço systemd
# (mesmo mecanismo de service_linux.py, chamado no fim daqui — pede a senha
# via sudo só nesse passo; depois disso o systemd sobe o serviço sozinho
# a cada boot, sem precisar de senha nenhuma de novo) e instala um ícone no
# menu de aplicativos (KDE/GNOME/XFCE/etc., ver controller-machine.desktop.
# template) que abre a janela (--gui, ver main.py::run_linux_gui) como
# visualizador/controle remoto desse mesmo serviço.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${1:-$HOME/.thenorian/controller}"

echo "Controller Machine — instalador"
echo
echo "Isto vai instalar o Controller Machine em: $INSTALL_DIR"
echo "  - Cria a pasta de instalação e uma pasta logs/ dentro dela"
echo "  - Cria um ambiente virtual Python isolado (venv) e instala as dependências"
echo "  - Registra como serviço systemd, iniciando sozinho com o sistema"
echo "    (vai pedir sua senha via sudo só nesse último passo)"
echo
read -r -p "Continuar? [s/N] " confirm
case "$confirm" in
    [sS]|[sS][iI][mM]) ;;
    *) echo "Instalação cancelada."; exit 0 ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 não encontrado. Instale o Python 3 e rode este script de novo." >&2
    exit 1
fi

# tkinter é do próprio Python, mas a maioria das distros empacota separado
# do python3 base (ex.: apt não traz por padrão) - sem isso o app gráfico
# (--gui) não abre, mesmo com o serviço rodando normalmente. cups.h é o
# cabeçalho de desenvolvimento que o pycups precisa pra compilar (listar
# impressora instalada no CUPS, ver discovery.py) - sem ele o pip install
# do pycups falha. Os dois são só avisos: a instalação segue mesmo assim
# (o serviço/impressão em si não depende de nenhum dos dois).
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo
    echo "AVISO: tkinter não encontrado - o app gráfico (ícone no menu) não vai abrir."
    echo "  Debian/Ubuntu: sudo apt install python3-tk"
    echo "  Arch:          sudo pacman -S tk"
    echo "  Fedora:        sudo dnf install python3-tkinter"
fi
if [ ! -f /usr/include/cups/cups.h ] && [ ! -f /usr/local/include/cups/cups.h ]; then
    echo
    echo "AVISO: cabeçalho de desenvolvimento do CUPS não encontrado - a instalação"
    echo "do pycups (lista de impressoras no diálogo de dispositivo) pode falhar."
    echo "  Debian/Ubuntu: sudo apt install libcups2-dev"
    echo "  Arch:          sudo pacman -S cups"
    echo "  Fedora:        sudo dnf install cups-devel"
fi

echo
echo "Copiando arquivos para $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR/logs"
cp -r "$SCRIPT_DIR/app/." "$INSTALL_DIR/"

echo "Criando ambiente virtual e instalando dependências..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements-client.txt"

echo
echo "Registrando serviço systemd (precisa de root)..."
sudo "$INSTALL_DIR/venv/bin/python3" "$INSTALL_DIR/main.py" --install-service

echo
echo "Instalando ícone no menu de aplicativos (KDE/GNOME/XFCE/etc.)..."
DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"
sed \
    -e "s#{venv_python}#$INSTALL_DIR/venv/bin/python3#g" \
    -e "s#{main_py}#$INSTALL_DIR/main.py#g" \
    -e "s#{icon_path}#$INSTALL_DIR/assets/icon.png#g" \
    "$SCRIPT_DIR/controller-machine.desktop.template" > "$DESKTOP_DIR/controller-machine.desktop"
chmod +x "$DESKTOP_DIR/controller-machine.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" || true

echo
echo "Instalação concluída."
echo "Logs em: $INSTALL_DIR/logs"
echo "Configuração em: /etc/controller-machine/config.json"
echo "App gráfico: procure \"Controller Machine\" no menu de aplicativos,"
echo "ou rode direto: $INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/main.py --gui"
