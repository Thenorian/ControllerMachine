#!/bin/bash
# Instalador Linux do Controller Machine — roda a partir do .tar.gz gerado
# por installer/build_linux_package.py (contém este script + a pasta app/
# com o código do client). Cria a instalação em ~/.thenorian/controller,
# um venv isolado com as dependências, e registra como serviço systemd
# (mesmo mecanismo de service_linux.py, chamado no fim daqui — pede a senha
# via sudo só nesse passo; depois disso o systemd sobe o serviço sozinho
# a cada boot, sem precisar de senha nenhuma de novo).
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
echo "Instalação concluída."
echo "Logs em: $INSTALL_DIR/logs"
echo "Configuração em: /etc/controller-machine/config.json"
