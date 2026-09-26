# -*- coding: utf-8 -*-
"""hal/base_camera.py — Contrato ABC para todos los backends de cámara."""
from __future__ import annotations
from abc import ABC, abstractmethod


class BaseCamera(ABC):
    @abstractmethod
    def open(self) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
    @abstractmethod
    def read_frame_bgr(self): ...
    @property
    def needs_streaming(self) -> bool: return False
    def start_capture(self) -> None: pass
    def stop_capture(self) -> None: pass

    @abstractmethod
    def safe_shutdown(self) -> None:
        """
        Deja la cámara en estado seguro y la cierra.

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
        close() y lo diga en una línea.
        """
        ...
