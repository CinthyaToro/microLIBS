# -*- coding: utf-8 -*-
"""hal/base_laser.py — Contrato ABC para drivers de láser."""
from __future__ import annotations
from abc import ABC, abstractmethod


class BaseLaser(ABC):
    @abstractmethod
    def connect(self, params: dict) -> None: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
    @abstractmethod
    def fire(self, pulse_us: int, delay_us: int = 0) -> dict: ...
    @abstractmethod
    def arm(self) -> None: ...
    @abstractmethod
    def disarm(self) -> None: ...

    @abstractmethod
    def fire_burst(self, n_pulsos: int) -> dict:
        """
        Dispara un burst de n_pulsos a la frecuencia propia del láser.
        El láser debe estar armado antes de llamar este método.
        Retorna dict con el resultado (ok, elapsed_ms, n_pulsos, etc.).
        """
        ...

    @property
    @abstractmethod
    def rep_rate_hz(self) -> float:
        """Frecuencia de disparo en Hz a la que opera este láser."""
        ...

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
