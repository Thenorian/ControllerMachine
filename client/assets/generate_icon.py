"""
Gera o ícone pixel-art (estilo retrô) usado na bandeja do Windows e na janela
do Controller Machine — sem depender de nenhum arquivo de imagem externo, só
Pillow. Referência visual: o ícone clássico de "Meu Computador" do Windows
XP/98 (monitor CRT bege) com uma engrenagem sobreposta no canto, indicando
"controlador/configuração".

Desenhado numa grade baixa (32x32) com formas sólidas sem anti-aliasing e
depois escalado com NEAREST — é isso que garante o visual "blocado"/pixelado
em qualquer tamanho, igual ícone de sistema operacional antigo.

Rodar `python generate_icon.py` gera `icon.ico` (multi-resolução, pro
Windows) e `icon.png` (pro tray/janela no Linux) nesta mesma pasta. O
`tray.py` também pode chamar `build_icon_image()` direto em memória, sem
precisar dos arquivos no disco.
"""
from __future__ import annotations

import math
from pathlib import Path

GRID_SIZE = 32

# Paleta bege/cinza de plástico de CRT antigo + engrenagem laranja (mesmo
# espírito retrô, mas contrastando o suficiente pra ler bem em 16px).
CASE = (206, 201, 184, 255)
CASE_SHADOW = (150, 146, 130, 255)
CASE_HIGHLIGHT = (230, 226, 212, 255)
BEZEL = (58, 56, 64, 255)
SCREEN = (22, 38, 92, 255)
SCREEN_GLARE = (108, 148, 214, 255)
VENT = (120, 116, 104, 255)
GEAR = (224, 150, 40, 255)
GEAR_SHADOW = (156, 96, 20, 255)
TRANSPARENT = (0, 0, 0, 0)


def _draw_monitor(draw) -> None:
    # Corpo do monitor (case bege) com um filete de sombra/luz pra dar volume
    # mesmo sem anti-aliasing.
    draw.rectangle([2, 2, 25, 21], fill=CASE)
    draw.line([2, 21, 25, 21], fill=CASE_SHADOW)
    draw.line([25, 2, 25, 21], fill=CASE_SHADOW)
    draw.line([2, 2, 25, 2], fill=CASE_HIGHLIGHT)
    draw.line([2, 2, 2, 21], fill=CASE_HIGHLIGHT)

    # Moldura + tela (com "brilho" diagonal clássico de ícone de monitor)
    draw.rectangle([5, 5, 22, 16], fill=BEZEL)
    draw.rectangle([6, 6, 21, 15], fill=SCREEN)
    for i in range(5):
        draw.point((7 + i, 14 - i), fill=SCREEN_GLARE)
        draw.point((8 + i, 14 - i), fill=SCREEN_GLARE)

    # Grade de ventilação (detalhe clássico do case)
    for x in (4, 6, 8):
        draw.point((x, 19), fill=VENT)
        draw.point((x, 20), fill=VENT)

    # Pescoço + base (o "pé" do monitor CRT)
    draw.rectangle([11, 22, 16, 23], fill=CASE_SHADOW)
    draw.rectangle([7, 24, 20, 26], fill=CASE)
    draw.line([7, 24, 20, 24], fill=CASE_HIGHLIGHT)
    draw.line([7, 24, 7, 26], fill=CASE_SHADOW)
    draw.line([20, 24, 20, 26], fill=CASE_SHADOW)


def _draw_gear(draw) -> None:
    # Engrenagem sobreposta no canto inferior direito, por cima do case —
    # é o que transforma "monitor genérico" em "controlador de dispositivo".
    cx, cy, r = 23, 23, 7
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GEAR, outline=GEAR_SHADOW)

    tooth = 2
    for angle_deg in range(0, 360, 45):
        rad = math.radians(angle_deg)
        tx = cx + (r - 1) * math.cos(rad)
        ty = cy + (r - 1) * math.sin(rad)
        draw.rectangle([tx - tooth / 2, ty - tooth / 2, tx + tooth / 2, ty + tooth / 2], fill=GEAR)

    hole_r = 2
    draw.ellipse([cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r], fill=TRANSPARENT)


def build_icon_image(scale: int = 8):
    from PIL import Image, ImageDraw

    base = Image.new("RGBA", (GRID_SIZE, GRID_SIZE), TRANSPARENT)
    draw = ImageDraw.Draw(base)
    _draw_monitor(draw)
    _draw_gear(draw)

    return base.resize((GRID_SIZE * scale, GRID_SIZE * scale), Image.NEAREST)


def main() -> None:
    image = build_icon_image()
    out_dir = Path(__file__).parent
    image.save(out_dir / "icon.png")
    image.save(out_dir / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
    print(f"Ícone gerado em {out_dir}/icon.png e {out_dir}/icon.ico")


if __name__ == "__main__":
    main()
