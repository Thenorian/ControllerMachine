# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ControllerMachine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\icon.ico'],
)

# --onedir, não --onefile: o modo antigo (EXE com a.binaries/a.datas direto,
# sem COLLECT) extraía a stdlib pra %TEMP%\_MEIxxxxxx a cada execução e lia
# os módulos dali sob demanda - num PDV em produção essa pasta foi apagada
# (antivírus ou faxina de temporários do Windows) enquanto o processo ainda
# rodava, e todo encoding ainda não usado até aquele momento passou a
# quebrar pra sempre com FileNotFoundError (ver _pre_carregar_codecs_impressao
# em main.py, que amenizava mas não resolvia a causa). Com COLLECT, o
# conteúdo fica em disco de verdade ao lado do .exe (pasta _internal/,
# dentro da própria instalação) e nunca precisa ser extraído de novo nem
# depende do %TEMP% sobreviver o tempo todo que o processo roda.
COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ControllerMachine',
)
