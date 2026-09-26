# -*- coding: utf-8 -*-
"""
capacidades.py — los CONTRATOS (qué sabe hacer cada cosa), sin marca.
El resto del sistema habla SOLO con estas clases, nunca con Ocean/EKSPLA directo.
"""
from abc import ABC, abstractmethod


class Firing(ABC):
    """Capacidad: disparar el láser."""

    @abstractmethod
    def arm(self) -> None:
        """Prepara el láser para disparar. NO dispara."""

    @abstractmethod
    def fire_burst(self, n: int) -> None:
        """Dispara una ráfaga de n pulsos. Operación ATÓMICA: entera o nada."""

    @abstractmethod
    def safe_off(self) -> None:
        """Deja el láser en estado seguro (output off). Siempre se puede llamar."""


class Acquiring(ABC):
    """Capacidad: adquirir un espectro."""

    @abstractmethod
    def set_trigger_externo(self, activado: bool) -> None:
        """Configura adquisición gatillada por trigger externo (hardware)."""

    @abstractmethod
    def set_ventana_us(self, ventana_us: int) -> None:
        """Tiempo de integración / ventana de adquisición, en microsegundos."""

    @abstractmethod
    def armar(self) -> None:
        """Arranca la adquisición: queda ESPERANDO el trigger."""

    @abstractmethod
    def leer_espectro(self, timeout_s: float):
        """Devuelve (longitudes_onda, intensidades) o lanza TimeoutError."""
