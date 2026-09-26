# -*- coding: utf-8 -*-
"""
application/platform_profile.py
=================================
PlatformProfile — Embrión del Instrument Domain (MCA).

Describe las capacidades del hardware seleccionado para una sesión.
Todo procedimiento (calibración, jog, scan, ROI) consulta este perfil
para mostrar solo los controles coherentes con el hardware activo.

Esto evita el problema de ver parámetros de MoVi cuando se usa Thorlabs,
o controles de 3 ejes cuando el stage solo tiene X/Y.

Uso:
    profile = PlatformProfile.from_hardware(stage, camera_backend="opencv")
    profile.has_axis("z")          # → False para MoVi
    profile.calib_method           # → "ruler" para MoVi, "stage" para Thorlabs
    profile.jog_step_default_mm    # → 1.0 para MoVi, 0.1 para Thorlabs
    profile.can_reach(x_mm, y_mm)  # → False si está fuera del rango físico
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Defaults por driver (usados si no se puede derivar del objeto stage)
# ---------------------------------------------------------------------------

_DRIVER_DEFAULTS = {
    "movi": {
        "axes":                    ["x", "y"],
        "has_homing":              {"x": False, "y": False},
        "range_mm":                {"x": (-35.0, 35.0), "y": (-35.0, 35.0)},
        "calib_method":            "ruler",
        "jog_step_default_mm":     1.0,
        "jog_step_fine_mm":        0.1,
        "jog_step_coarse_mm":      5.0,
        "calib_move_dx_mm":        10.0,
        "calib_move_dy_mm":        10.0,
        "invert_y_axis":           False,
        "notes": (
            "MoVi: posición comandada (sin encoder ni fines de carrera). "
            "Error mecánico: 230–500 µm (X ≠ Y). "
            "Recalibrar si se notan errores de posición acumulados."
        ),
    },
    "thorlabs": {
        "axes":                    ["x", "y", "z"],
        "has_homing":              {"x": True, "y": True, "z": True},
        "range_mm":                {"x": (0.0, 4.0), "y": (0.0, 4.0), "z": (0.0, 4.0)},
        "calib_method":            "stage",
        "jog_step_default_mm":     0.1,
        "jog_step_fine_mm":        0.01,
        "jog_step_coarse_mm":      0.5,
        "calib_move_dx_mm":        1.0,
        "calib_move_dy_mm":        1.0,
        "invert_y_axis":           True,   # eje Y físico invertido respecto de imagen
        "notes": (
            "Thorlabs Kinesis: rango 4×4×4 mm. "
            "Home (0,0,0) = límite físico. Solo coordenadas positivas. "
            "Ejecutar Home antes de cada sesión. "
            "⚠ Eje Y físicamente invertido respecto de imagen de cámara."
        ),
    },
    "thorlabs_sim": {
        "axes":                    ["x", "y", "z"],
        "has_homing":              {"x": True, "y": True, "z": True},
        "range_mm":                {"x": (0.0, 4.0), "y": (0.0, 4.0), "z": (0.0, 4.0)},
        "calib_method":            "stage",
        "jog_step_default_mm":     0.1,
        "jog_step_fine_mm":        0.01,
        "jog_step_coarse_mm":      0.5,
        "calib_move_dx_mm":        1.0,
        "calib_move_dy_mm":        1.0,
        "invert_y_axis":           True,
        "notes": "Thorlabs simulado: 4×4×4 mm, solo positivos. Y invertido.",
    },
    "sim": {
        "axes":                    ["x", "y"],
        "has_homing":              {"x": False, "y": False},
        "range_mm":                {"x": (-50.0, 50.0), "y": (-50.0, 50.0)},
        "calib_method":            "ruler",
        "jog_step_default_mm":     1.0,
        "jog_step_fine_mm":        0.1,
        "jog_step_coarse_mm":      5.0,
        "calib_move_dx_mm":        5.0,
        "calib_move_dy_mm":        5.0,
        "invert_y_axis":           False,
        "notes": "Stage simulado: acepta cualquier coordenada.",
    },
}

_DEFAULT_FALLBACK = _DRIVER_DEFAULTS["sim"]


# ---------------------------------------------------------------------------
# PlatformProfile
# ---------------------------------------------------------------------------

@dataclass
class PlatformProfile:
    """
    Perfil de capacidades de la plataforma activa.

    Atributos derivados del hardware real; los procedimientos (calibración,
    jog, scan) los consultan para adaptar la UI y la lógica.
    """

    # ── hardware ──────────────────────────────────────────────────────────
    stage_driver: str = ""
    camera_backend: str = ""
    laser_controlled: bool = False
    spectrometer_controlled: bool = False

    # ── capacidades del stage ────────────────────────────────────────────
    axes: List[str] = field(default_factory=lambda: ["x", "y"])
    has_homing: Dict[str, bool] = field(default_factory=dict)
    range_mm: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    # ── calibración recomendada ──────────────────────────────────────────
    calib_method: str = "ruler"        # "ruler" | "stage"
    calib_move_dx_mm: float = 5.0      # distancia de movimiento en X para método stage
    calib_move_dy_mm: float = 5.0      # distancia de movimiento en Y para método stage

    # ── jog ──────────────────────────────────────────────────────────────
    jog_step_default_mm: float = 1.0
    jog_step_fine_mm: float = 0.1
    jog_step_coarse_mm: float = 5.0

    # ── corrección de ejes ────────────────────────────────────────────────
    invert_y_axis: bool = False   # True cuando el eje Y físico es inverso al de imagen

    # ── scan simulado ─────────────────────────────────────────────────────
    sim_dwell_ms: int = 500    # espera por punto cuando láser/espectrómetro son simulados

    # ── documentación ────────────────────────────────────────────────────
    notes: str = ""

    # ----------------------------------------------------------------
    # Constructor desde objetos de hardware
    # ----------------------------------------------------------------

    @classmethod
    def from_hardware(
        cls,
        stage=None,
        camera_backend: str = "",
        laser_controlled: bool = False,
        spectrometer_controlled: bool = False,
    ) -> "PlatformProfile":
        """
        Crea un PlatformProfile derivando las capacidades del objeto stage.
        Si stage es None, retorna un perfil mínimo (solo cámara / regla).
        """
        prof = cls()
        prof.camera_backend = camera_backend
        prof.laser_controlled = laser_controlled
        prof.spectrometer_controlled = spectrometer_controlled

        if stage is None:
            prof.stage_driver = "none"
            prof.axes = []
            prof.has_homing = {}
            prof.range_mm = {}
            prof.calib_method = "ruler"
            prof.notes = "Sin stage: solo calibración por regla disponible."
            return prof

        # Identificar driver
        driver = stage.__class__.__name__.lower().replace("stage", "").strip()
        prof.stage_driver = driver
        defaults = _DRIVER_DEFAULTS.get(driver, _DEFAULT_FALLBACK)

        # Ejes disponibles: primero del objeto, luego de defaults
        prof.axes = [ax for ax in getattr(stage, "AXES", defaults["axes"])]

        # Homing por eje: consultar el objeto stage
        prof.has_homing = {}
        for ax in prof.axes:
            try:
                prof.has_homing[ax] = bool(stage.has_homing(ax))
            except Exception:
                prof.has_homing[ax] = defaults.get("has_homing", {}).get(ax, False)

        # Rangos: primero de _DRIVER_DEFAULTS, luego fallback genérico
        d_range = defaults.get("range_mm", {"x": (-35.0, 35.0), "y": (-35.0, 35.0)})
        prof.range_mm = {ax: d_range.get(ax, (-35.0, 35.0)) for ax in prof.axes}

        # UI defaults
        prof.calib_method      = defaults["calib_method"]
        prof.calib_move_dx_mm  = defaults["calib_move_dx_mm"]
        prof.calib_move_dy_mm  = defaults["calib_move_dy_mm"]
        prof.jog_step_default_mm = defaults["jog_step_default_mm"]
        prof.jog_step_fine_mm    = defaults["jog_step_fine_mm"]
        prof.jog_step_coarse_mm  = defaults["jog_step_coarse_mm"]
        prof.invert_y_axis       = defaults.get("invert_y_axis", False)
        prof.notes               = defaults["notes"]

        return prof

    # ----------------------------------------------------------------
    # Consultas
    # ----------------------------------------------------------------

    def has_axis(self, axis: str) -> bool:
        """True si el stage tiene ese eje."""
        return axis.lower() in self.axes

    def homing_available(self, axis: str) -> bool:
        """True si el stage puede hacer Home en ese eje."""
        return bool(self.has_homing.get(axis.lower(), False))

    def can_reach(self, x_mm: float, y_mm: float) -> bool:
        """
        Verifica si el stage puede alcanzar (x_mm, y_mm).
        Si no hay rangos definidos, retorna True (no restricción).
        """
        if not self.range_mm:
            return True
        xr = self.range_mm.get("x", (-9999.0, 9999.0))
        yr = self.range_mm.get("y", (-9999.0, 9999.0))
        return xr[0] <= x_mm <= xr[1] and yr[0] <= y_mm <= yr[1]

    def range_label(self, axis: str) -> str:
        """Etiqueta de rango para UI: 'X: -35.0 … 35.0 mm'."""
        r = self.range_mm.get(axis.lower())
        if r is None:
            return f"{axis.upper()}: sin límite"
        return f"{axis.upper()}: {r[0]:.1f} … {r[1]:.1f} mm"

    def has_stage(self) -> bool:
        return bool(self.axes) and self.stage_driver not in ("", "none")

    def has_z(self) -> bool:
        return self.has_axis("z")

    # ----------------------------------------------------------------
    # Serialización (para session.json / IKL)
    # ----------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "stage_driver":          self.stage_driver,
            "camera_backend":        self.camera_backend,
            "laser_controlled":      self.laser_controlled,
            "spectrometer_controlled": self.spectrometer_controlled,
            "axes":                  self.axes,
            "has_homing":            self.has_homing,
            "range_mm":              {k: list(v) for k, v in self.range_mm.items()},
            "calib_method":          self.calib_method,
            "calib_move_dx_mm":      self.calib_move_dx_mm,
            "calib_move_dy_mm":      self.calib_move_dy_mm,
            "jog_step_default_mm":   self.jog_step_default_mm,
            "jog_step_fine_mm":      self.jog_step_fine_mm,
            "jog_step_coarse_mm":    self.jog_step_coarse_mm,
            "sim_dwell_ms":          self.sim_dwell_ms,
            "notes":                 self.notes,
        }

    def summary(self) -> str:
        parts = [
            f"Stage: {self.stage_driver or 'ninguno'}",
            f"Cámara: {self.camera_backend or 'ninguna'}",
        ]
        if self.axes:
            parts.append(f"Ejes: {', '.join(a.upper() for a in self.axes)}")
            home_axes = [a.upper() for a in self.axes if self.homing_available(a)]
            parts.append(f"Home: {', '.join(home_axes) if home_axes else 'no disponible'}")
        parts.append(f"Calibración recomendada: {self.calib_method}")
        if self.notes:
            parts.append(self.notes)
        return " | ".join(parts)
