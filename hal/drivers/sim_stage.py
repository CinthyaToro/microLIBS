# -*- coding: utf-8 -*-
"""hal/drivers/sim_stage.py — Stage simulado para testing sin hardware."""
import time
from hal.base_stage import BaseStage


class SimStage(BaseStage):
    AXES = ("x", "y", "z")

    def __init__(self):
        self._pos = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._connected = False

    def connect(self, params: dict) -> None:
        self._connected = True
        print("SimStage: conectado (modo simulación).")

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def home(self, axis: str) -> None:
        ax = axis.lower()
        if ax in self.AXES:
            self._pos[ax] = 0.0

    def has_homing(self, axis: str) -> bool:
        return True

    def move_abs(self, axis: str, pos_mm: float) -> None:
        ax = axis.lower()
        if ax not in self.AXES:
            raise ValueError("SimStage: eje '%s' no soportado." % axis)
        time.sleep(0.02)
        self._pos[ax] = float(pos_mm)

    def move_rel(self, axis: str, delta_mm: float) -> None:
        ax = axis.lower()
        self.move_abs(ax, self._pos.get(ax, 0.0) + delta_mm)

    def stop(self, axis: str) -> None:
        pass

    def position(self, axis: str) -> float:
        ax = axis.lower()
        if ax not in self.AXES:
            raise ValueError("SimStage: eje '%s' no existe." % axis)
        return self._pos.get(ax, 0.0)

    # ── Apagado seguro ──────────────────────────────────────────────────────
    def safe_shutdown(self) -> None:
        """
        Apagado seguro: mismo gesto que el hardware real (homear x e y y
        desconectar), sin hilos porque aca es instantaneo. R9: el gemelo
        simulado hace la misma secuencia que el real.
        """
        for _ax in ("x", "y"):
            try:
                self.home(_ax)
            except Exception:
                pass
        self.disconnect()
