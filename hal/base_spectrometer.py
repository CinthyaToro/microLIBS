# -*- coding: utf-8 -*-
"""hal/base_spectrometer.py — Contrato ABC para espectrómetros."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Tuple


class BaseSpectrometer(ABC):
    @abstractmethod
    def connect(self, params: dict) -> None: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
    @abstractmethod
    def acquire(self, integration_ms: float, averages: int = 1) -> dict: ...
    @abstractmethod
    def get_wavelengths(self) -> list: ...

    # ── Acquisition delay (opcional — degradá con gracia si no soportado) ──────

    def supports_acquisition_delay(self) -> bool:
        """True si el equipo soporta configurar el delay de adquisición."""
        return False

    def set_acquisition_delay_us(self, us: int) -> None:
        """Fija el delay entre trigger TTL e inicio de integración (µs).
        No-op si supports_acquisition_delay() es False."""

    def get_acquisition_delay_limits_us(self) -> Tuple[int, int, int]:
        """Retorna (min_us, max_us, increment_us). (0, 0, 1) si no soportado."""
        return (0, 0, 1)
    
    def get_acquisition_delay_us(self) -> int:
        """Lee el delay de adquisición actualmente configurado en el hardware (µs).
        Retorna 0 si no soportado."""
        return 0

    @abstractmethod
    def safe_shutdown(self) -> None:
        """
        Deja el instrumento en estado seguro y lo cierra.

        Es la receta de apagado de ESTE instrumento: solo el driver sabe qué
        necesita su hardware. El orquestador (`service/shutdown_service.py`)
        únicamente decide el ORDEN entre instrumentos y llama a este método;
        no conoce marcas ni modelos. Eso es R2 — por capacidad, no por marca.

        Contrato:
          - Intenta TODOS sus pasos aunque alguno falle (try/except por paso).
          - Es idempotente: llamarlo dos veces no rompe nada.
          - Puede lanzar; el orquestador lo captura y lo registra.
          - Después de esto el instrumento queda cerrado.

        Es abstracto a propósito: un driver nuevo no puede olvidarse de
        declarar cómo se apaga. Si no necesita nada especial, que llame a
        disconnect() y lo diga en una línea.
        """
        ...

