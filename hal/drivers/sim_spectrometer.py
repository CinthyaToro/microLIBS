# -*- coding: utf-8 -*-
"""
hal/drivers/sim_spectrometer.py  —  SimSpectrometer
====================================================
Gemelo simulado del espectrómetro Ocean HR2000+ (R9).

Implementa exactamente la misma interfaz que OceanSpectrometer pero
sin hablar con ningún hardware. Útil para desarrollar y probar el flujo
completo (FIRE + ADQUIRIR → GUARDAR → GRAFICACAR) en la Dell sin el rack.

Diferencias respecto a OceanSpectrometer(simulate=True):
- Siempre simula; no acepta simulate=False en connect().
- Usa rng_seed=42 por defecto → espectros reproducibles sesión a sesión.
- acquire() retorna de inmediato (no bloquea esperando trigger TTL).
- Se identifica claramente en logs: repr() muestra "SimSpectrometer".

Comportamiento modo-dependiente (para probar dark subtraction):
- trigger_mode == 0 (free-running / dark): baseline plana ~200 cuentas, sin picos.
  Simula captura de fondo con láser apagado.
- trigger_mode != 0 (HW-edge / post-disparo): baseline + picos gaussianos.
  Simula espectro de plasma.

Uso desde factory.py:
    spec = create_spectrometer("sim")
    spec.connect({"output_dir": session_dir, "integration_us": 5000})
    data = spec.acquire(integration_ms=5.0)
    # data["channels"]["A"]["wavelengths"] = [294.0, ..., 390.1]  # 2048 pts
    # data["channels"]["A"]["intensities"] = [210.3, ..., 850.2]
"""

from __future__ import annotations

import random as _random
from datetime import datetime

from hal.base_spectrometer import BaseSpectrometer
from hal.drivers.ocean_spectrometer import (
    OceanSpectrometer, TRIGGER_FREE_RUNNING, TRIGGER_HW_EDGE,
)

_DARK_BASELINE  = 200.0   # cuentas de fondo típicas del HR2000+
_DARK_NOISE     = 25.0    # ± cuentas de ruido en el dark


class SimSpectrometer(BaseSpectrometer):
    """
    Espectrómetro simulado: delega en OceanSpectrometer(simulate=True)
    para espectros con picos. En modo free-running (dark) genera
    baseline plana para permitir probar la resta de fondo.

    Canales: A (294–390 nm), B (520–636 nm), C (624–729 nm) — 2048 pts c/u.
    Formato de retorno idéntico al de OceanSpectrometer.acquire().
    """

    def __init__(self, rng_seed: int = 42):
        self._inner = OceanSpectrometer()
        self._rng_seed = rng_seed
        self._sim_delay_us: int = 0
        self._sim_trigger_mode: int = TRIGGER_HW_EDGE  # default LIBS

    # ── BaseSpectrometer API ──────────────────────────────────────────────────

    def connect(self, params: dict) -> None:
        """
        Conecta el espectrómetro simulado.

        Parámetros útiles del dict params:
            output_dir      str  Directorio donde guardar CSV de espectros
            integration_us  int  Tiempo de integración (informativo, no bloquea)
            n_channels      int  Cuántos módulos simular (default: 3)
            trigger_mode    int  Modo inicial (default: TRIGGER_HW_EDGE = 3)
        """
        forced = dict(params)
        forced["simulate"] = True
        forced.setdefault("rng_seed", self._rng_seed)
        forced.setdefault("n_channels", 3)
        self._sim_trigger_mode = int(params.get("trigger_mode", TRIGGER_HW_EDGE))
        self._inner.connect(forced)

    def disconnect(self) -> None:
        self._inner.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._inner.is_connected

    def acquire(self, integration_ms: float = 5.0, averages: int = 1) -> dict:
        """
        Adquiere un espectro simulado. Retorna inmediatamente (no bloquea).

        Modo free-running (trigger_mode == 0): baseline plana sin picos — dark.
        Modo HW-edge  (trigger_mode != 0): baseline + picos gaussianos — señal.
        """
        if self._sim_trigger_mode == TRIGGER_FREE_RUNNING:
            return self._acquire_dark()
        return self._inner.acquire(integration_ms=integration_ms, averages=averages)

    def get_wavelengths(self) -> list:
        return self._inner.get_wavelengths()

    # ── Métodos extra (misma interfaz que OceanSpectrometer) ─────────────────

    def set_trigger_mode(self, mode: int) -> None:
        self._sim_trigger_mode = int(mode)
        self._inner.set_trigger_mode(mode)

    def get_trigger_mode(self) -> int:
        """Último modo de trigger comandado (mismo significado que en OceanSpectrometer)."""
        return self._sim_trigger_mode

    def set_integration(self, us: int) -> None:
        self._inner.set_integration(us)

    def arm_trigger(self) -> None:
        """No-op en simulación."""

    def reset_to_free_running(self) -> None:
        """No-op en simulación."""

    # ── Acquisition delay simulado ────────────────────────────────────────────

    def supports_acquisition_delay(self) -> bool:
        return True

    def set_acquisition_delay_us(self, us: int) -> None:
        self._sim_delay_us = max(0, min(100_000, us))

    def get_acquisition_delay_limits_us(self):
        return (0, 100_000, 1)

    def channel_info(self) -> list:
        return self._inner.channel_info()

    def __repr__(self) -> str:
        chs = [m.channel for m in self._inner._modules]
        return "SimSpectrometer(channels=%s, connected=%s, seed=%d, mode=%d)" % (
            chs, self._inner.is_connected, self._rng_seed, self._sim_trigger_mode
        )

    # ── Dark simulado (modo free-running) ─────────────────────────────────────

    def _acquire_dark(self) -> dict:
        """Genera espectro de fondo: baseline plana ~200 cts ± ruido, sin picos."""
        rng = _random.Random(self._rng_seed + 1)   # semilla distinta de la señal
        channels = {}
        for m in self._inner._modules:
            if not m.wavelengths:
                continue
            ints = [_DARK_BASELINE + rng.uniform(-_DARK_NOISE, _DARK_NOISE)
                    for _ in m.wavelengths]
            channels[m.channel] = {
                "ok":          True,
                "wavelengths": list(m.wavelengths),
                "intensities": ints,
                "range_nm":    (m.wavelengths[0], m.wavelengths[-1]),
                "serial":      m.serial,
                "error":       None,
            }
        return {
            "ok":            True,
            "channels":      channels,
            "csv_path":      None,
            "timestamp_iso": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "integration_ms": self._inner._params.get("integration_us", 5000) / 1000.0,
            "averages":      1,
            "trigger_mode":  TRIGGER_FREE_RUNNING,
        }

    # ── Apagado seguro ──────────────────────────────────────────────────────
    # En el real esto es 0.2 s, para que el USB procese el cambio de modo
    # antes de cerrar. Aca no hay USB que esperar: la espera es una
    # particularidad del hardware, no parte de la secuencia logica. Se deja
    # el atributo para que la forma sea la misma que la del real (R9).
    ESPERA_USB_S = 0.0

    def safe_shutdown(self) -> None:
        """
        Apagado seguro del HR2000+: sacarlo del modo trigger, darle tiempo al
        USB, y recien ahi cerrar. Ver BaseSpectrometer.

        PENDIENTE (necesita hardware): si hay una adquisicion bloqueada
        esperando el TTL en modo 3, disconnect() espera el _lock y el cierre
        puede tardar. No se arregla con una bandera de Python: el bloqueo esta
        dentro de self.spec.intensities(), en C. Mientras tanto el orquestador
        acota cuanto espera. Ver docs/bitacora/2026-09-22.md, pendiente 9.
        """
        import time as _time
        try:
            self.set_trigger_mode(0)
        except Exception:
            pass
        _time.sleep(self.ESPERA_USB_S)
        self.disconnect()
