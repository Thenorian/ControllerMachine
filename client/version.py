"""
Versão atual do Controller Machine — única fonte de verdade, comparada
pelo updater.py contra a tag da última release no GitHub
(https://github.com/Thenorian/ControllerMachine/releases). Sempre
atualizar ESTE arquivo (num commit próprio, ex.: "Bump version pra vX.Y")
antes de criar a tag/release `vX.Y` — o CI (.github/workflows/
build-packages.yml) confere que os dois batem e falha o build se
esquecer (ver job `confere-versao`).
"""
__version__ = "1.4"
