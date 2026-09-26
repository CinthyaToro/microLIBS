# -*- coding: utf-8 -*-
"""
hal/drivers/sim_laser.py  —  SimLaser
======================================
Implementación simulada de BaseLaser para testing sin hardware.

Reproduce fielmente la interfaz de LaserProxy pero sin DLL ni socket.
Útil para desarrollar y probar el pipeline de scan en modo offline.
"""

from __future__ import annotations

import time
from hal.base_laser import BaseLaser


class SimLaser(BaseLaser):
    """Láser simulado: acepta todos los comandos, registra llamadas."""

    def __init__(self, fire_delay_s: float = 0.05):
        """
        fire_delay_s  — tiempo que simula el disparo (default: 50 ms).
        """
        self._fire_delay_s   = fire_delay_s
        self._connected      = False
        self._armed          = False
        self._fire_count     = 0
        self._params: dict   = {}

    # ── BaseLaser ────────────────────────────────────────────────────────────

    def connect(self, params: dict) -> None:
        self._params    = dict(params)
        self._connected = True
        self._armed     = False
        if params.get("auto_arm", False):
            self.arm()

    def disconnect(self) -> None:
        if self._armed:
            self.disarm()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def arm(self) -> None:
        if not self._connected:
            raise RuntimeError("SimLaser: no conectado.")
        self._armed = True

    def disarm(self) -> None:
        self._armed = False

    def fire(self, pulse_us: int = 0, delay_us: int = 0) -> dict:
        if not self._connected:
            return {"ok": False, "error": "No conectado", "pulse_us": pulse_us}
        if not self._armed:
            return {"ok": False, "error": "Láser no armado", "pulse_us": pulse_us}

        t0 = time.perf_counter()
        # Simula el tiempo de disparo + delay adicional
        total_s = self._fire_delay_s + delay_us / 1_000_000.0
        time.sleep(total_s)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self._fire_count += 1

        return {
            "ok":          True,
            "simulated":   True,
            "pulse_us":    pulse_us,
            "delay_us":    delay_us,
            "elapsed_ms":  round(elapsed_ms, 2),
            "fire_count":  self._fire_count,
        }

    def fire_burst(self, n_pulsos: int) -> dict:
        """
        Simula un burst de n_pulsos a 100 Hz.
        El láser debe estar armado antes de llamar este método.
        """
        if not self._connected:
            return {"ok": False, "error": "No conectado", "n_pulsos": n_pulsos}
        if not self._armed:
            return {"ok": False, "error": "Láser no armado", "n_pulsos": n_pulsos}

        t0 = time.perf_counter()
        time.sleep(float(n_pulsos) / 100.0)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self._fire_count += n_pulsos

        return {
            "ok":          True,
            "simulated":   True,
            "n_pulsos":    n_pulsos,
            "rep_rate_hz": 100.0,
            "elapsed_ms":  round(elapsed_ms, 2),
            "fire_count":  self._fire_count,
        }

    @property
    def rep_rate_hz(self) -> float:
        """Frecuencia de disparo en Hz a la que opera este láser."""
        return 100.0

    # ── Extras compatibles con LaserProxy ────────────────────────────────────

    def get_state(self) -> dict:
        return {
            "power":          "ON" if self._armed else "OFF",
            "output_enable":  "OFF",
            "fault_source":   "NONE",
            "fault_code":     "0",
            "rep_rate_hz":    "10",
        }

    def get_register(self, module: str, register: str) -> str:
        return "SIM_VALUE"

    def set_register(self, module: str, register: str, value: str) -> None:
        pass

    def list_modules(self) -> list:
        return ["CPU8000:16 (sim)", "HV+4-4kV:40 (sim)", "UCP:4 (sim)"]

    def __repr__(self) -> str:
        return ("SimLaser(connected=%s, armed=%s, fires=%d)" % (
            self._connected, self._armed, self._fire_count))

    # ── Apagado seguro ──────────────────────────────────────────────────────
    # Registros del NL230 que se dejan en un estado seguro conocido antes de
    # desconectar, para que el equipo no quede armado. Extraidos de la
    # secuencia que vivia en presentation/main_window.py hasta 2026-09-22.
    _SHUTDOWN_MODULO = "CPU8000:16"
    _SHUTDOWN_REGISTROS = [
        ("Output enable",                           "OFF"),
        ("Continuous / Burst mode / Trigger burst", "Burst"),
        ("Burst length",                            "1"),
        ("Synchronization mode",                    "Internal"),
    ]

    def safe_shutdown(self) -> None:
        """
        Apagado seguro del EKSPLA NL230: desarmar, dejar los registros en
        estado seguro conocido, y recien ahi desconectar. Ver BaseLaser.
        """
        try:
            self.disarm()
        except Exception:
            pass
        for _reg, _val in self._SHUTDOWN_REGISTROS:
            try:
                self.set_register(self._SHUTDOWN_MODULO, _reg, _val)
            except Exception:
                pass
        self.disconnect()
