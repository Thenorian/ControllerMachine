from .base import get_formatter, list_brands, register_formatter

__all__ = ["get_formatter", "list_brands", "register_formatter"]

# Importar os módulos concretos registra os formatters (efeito colateral do
# @register_formatter em cada arquivo).
from . import filizola, ramuza_atena, toledo_mgv5  # noqa: E402,F401
