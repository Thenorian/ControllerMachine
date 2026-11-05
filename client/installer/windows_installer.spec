# -*- mode: python ; coding: utf-8 -*-
# Builda DEPOIS de client/ControllerMachine.spec — embute a pasta
# dist/ControllerMachine/ já pronta (ControllerMachine.exe + _internal/,
# ver ControllerMachine.spec) como dado (payload/), este instalador não
# compila o app, só empacota.

a = Analysis(
    ['windows_installer.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('../assets/icon.ico', '.'),
        ('../assets/icon.png', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Tree() devolve tuplas de 3 (formato TOC: dest, src, typecode) - não dá pra
# misturar com as tuplas de 2 (src, dest) do parâmetro datas= acima, dá
# "ValueError: too many values to unpack" (já bati nessa). Soma direto no
# a.datas (que já é TOC) depois do Analysis() pronto, igual a documentação
# do PyInstaller recomenda pra embutir uma pasta inteira.
a.datas += Tree('../dist/ControllerMachine', prefix='payload')
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ControllerMachineSetup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['..\\assets\\icon.ico'],
)
