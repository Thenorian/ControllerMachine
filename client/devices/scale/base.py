"""
Interface comum dos formatters de balança + registro por marca. O Simple ERP
manda sempre a mesma lista genérica de produtos (via
connector.send_scale_update) — quem decide o formato de bytes exato pra cada
equipamento é o formatter registrado aqui, escolhido pelo campo `brand` do
device no catálogo local (ver catalog.py).

Produto genérico esperado em `products`:
    {"plu": "0002", "description": "SPECIAL GOLD FILHO", "unit": "KG",
     "price": 13.90, "validity_days": 365}
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ScaleTransport:
    """Como o Controller Machine fala com o equipamento — preenchido a
    partir do campo `connection` do device cadastrado localmente."""
    kind: str  # "tcp" | "serial"
    host: str | None = None
    port: int | None = None
    serial_port: str | None = None
    baudrate: int = 9600


class ScaleFormatter(ABC):
    """Cada marca implementa `build_table`. `verified` indica se o layout foi
    conferido byte-a-byte contra uma amostra real de arquivo do fabricante
    (ver pasta `Exemplos Balança/` na raiz do repo) — quando False, o
    formatter funciona mas precisa de validação contra equipamento real
    antes de confiar em produção."""

    brand: str
    verified: bool

    @abstractmethod
    def build_table(self, products: list[dict]) -> bytes:
        ...


_REGISTRY: dict[str, ScaleFormatter] = {}


def register_formatter(formatter: ScaleFormatter) -> ScaleFormatter:
    _REGISTRY[formatter.brand] = formatter
    return formatter


def get_formatter(brand: str) -> ScaleFormatter:
    try:
        return _REGISTRY[brand]
    except KeyError:
        raise ValueError(f"marca de balança desconhecida: {brand!r} (disponíveis: {sorted(_REGISTRY)})")


def list_brands() -> list[str]:
    return sorted(_REGISTRY)
