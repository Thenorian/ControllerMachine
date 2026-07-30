"""
Gera o ícone pixel-art (estilo retrô) usado na bandeja do Windows e na janela
do Controller Machine. Desenhado à mão como uma grade 16x16 — sem depender de
nenhum arquivo de imagem externo, então funciona só com Pillow instalado.

Rodar `python generate_icon.py` gera `icon.ico` (multi-resolução, pro
Windows) e `icon.png` (pro tray/janela no Linux) nesta mesma pasta. O
`tray.py` também pode chamar `build_icon_image()` direto em memória, sem
precisar dos arquivos no disco.
"""
from __future__ import annotations

from pathlib import Path

# 16x16, um caractere por pixel. '.' = transparente.
#   # = corpo da impressora (cinza escuro)
#   = = topo (cinza claro)
#   P = papel (branco)
#   o = luz de status (verde)
_GRID = [
    "................",
    "................",
    "...========.....",
    "..#========#....",
    "..#========#....",
    "..##########....",
    "..#PPPPPPPP#....",
    "..#PPPPPPPP#....",
    "..##########....",
    "..#..........#..",
    "..#....o......#.",
    "..#..........#..",
    "..############..",
    "................",
    "................",
    "................",
]

_COLORS = {
    ".": (0, 0, 0, 0),
    "#": (55, 65, 81, 255),    # cinza escuro
    "=": (156, 163, 175, 255),  # cinza claro
    "P": (255, 255, 255, 255),  # branco
    "o": (34, 197, 94, 255),   # verde (mesmo tom usado no wiki do connector)
}


def build_icon_image(scale: int = 8):
    from PIL import Image

    grid = _GRID
    h = len(grid)
    w = len(grid[0])
    base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pixels = base.load()
    for y, row in enumerate(grid):
        for x, char in enumerate(row):
            pixels[x, y] = _COLORS.get(char, (0, 0, 0, 0))

    return base.resize((w * scale, h * scale), Image.NEAREST)


def main() -> None:
    image = build_icon_image()
    out_dir = Path(__file__).parent
    image.save(out_dir / "icon.png")
    image.save(out_dir / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (128, 128)])
    print(f"Ícone gerado em {out_dir}/icon.png e {out_dir}/icon.ico")


if __name__ == "__main__":
    main()
