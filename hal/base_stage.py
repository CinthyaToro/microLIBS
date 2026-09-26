# -*- coding: utf-8 -*-
"""hal/base_stage.py — Contrato ABC para todos los drivers de stage."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Tuple


class BaseStage(ABC):
    AXES: Tuple[str, ...] = ()

    @abstractmethod
    def connect(self, params: dict) -> None: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
    @abstractmethod
    def home(self, axis: str) -> None: ...
    def has_homing(self, axis: str) -> bool: return False
    @abstractmethod
    def move_abs(self, axis: str, pos_mm: float) -> None: ...
    @abstractmethod
    def move_rel(self, axis: str, delta_mm: float) -> None: ...
    @abstractmethod
    def stop(self, axis: str) -> None: ...
    @abstractmethod
    def position(self, axis: str) -> float: ...
    def has_axis(self, axis: str) -> bool: return axis.lower() in self.AXES
    def has_z(self) -> bool: return "z" in self.AXES

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

