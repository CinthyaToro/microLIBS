# -*- coding: utf-8 -*-
"""
service/platform_profile.py
============================
Perfil de plataforma versionado para Cal-A (calibracion homografica estatica).

Funciones:
    build_profile  -- construye el dict del perfil desde los artefactos de Cal-A
    save_profile   -- serializa a JSON versionado (_v1, _v2 ... sin sobrescribir)
    load_profile   -- carga y valida un perfil desde JSON
    recompute_H    -- reproduce H desde puntos_crudos (KPI-4: trazabilidad)

Esquema JSON completo documentado en el brief Cal-A §5.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import numpy as np


# ---------------------------------------------------------------------------
# build_profile
# ---------------------------------------------------------------------------

def build_profile(
    camara: Dict[str, Any],
    optica: Dict[str, Any],
    escala: Dict[str, Any],
    patron: Dict[str, Any],
    H: np.ndarray,
    puntos_crudos: Dict[str, List],
    metricas: Dict[str, Any],
    checks: Dict[str, Any],
    *,
    operador: str = "",
    geometria: str = "oblicua",
    version: int = 1,
) -> dict:
    """
    Construye el dict del Perfil de plataforma Cal-A.

    Parametros
    ----------
    camara        : dict con modelo, serial, resolucion, px_um, mascara_defectos
    optica        : dict con f_mm, iris_mm, f_num, difraccion_um
    escala        : dict con px_por_mm, um_por_px, aumento, fov_mm
    patron        : dict con tipo, casilla_mm, casillas, esquinas
    H             : ndarray (3,3) homografia px->mm
    puntos_crudos : {"px": [[u,v],...], "mm_nominal": [[x,y],...]}
    metricas      : dict con rms_um, rms_px, esquinas_detectadas, det_lineal, isotropia_xy
    checks        : dict con nitidez_ok, saturacion_ok, espejado_ok, escala_cross_ok
    operador      : nombre del operador (opcional)
    geometria     : descripcion de la geometria optica
    version       : numero de version del esquema (por defecto 1)
    """
    _require_ndarray(H, (3, 3), "H")
    _require_keys(puntos_crudos, ["px", "mm_nominal"], "puntos_crudos")

    H_list = H.tolist()
    px_list = [list(map(float, p)) for p in puntos_crudos["px"]]
    mm_list = [list(map(float, p)) for p in puntos_crudos["mm_nominal"]]

    return {
        "meta": {
            "version":   version,
            "fecha":     time.strftime("%Y-%m-%dT%H:%M:%S"),
            "operador":  operador,
            "geometria": geometria,
        },
        "camara":         dict(camara),
        "optica":         dict(optica),
        "escala":         dict(escala),
        "patron":         dict(patron),
        "homografia":     {"H": H_list, "modelo": "homografia"},
        "puntos_crudos":  {"px": px_list, "mm_nominal": mm_list},
        "metricas":       dict(metricas),
        "checks":         dict(checks),
    }


# ---------------------------------------------------------------------------
# save_profile
# ---------------------------------------------------------------------------

def save_profile(profile: dict, path: str) -> str:
    """
    Guarda el perfil en JSON. Si el archivo ya existe incrementa el sufijo de
    version: _v1.json, _v2.json, etc. Nunca sobrescribe.

    Retorna la ruta efectiva donde se guardo.
    """
    base, ext = os.path.splitext(path)
    if not ext:
        ext = ".json"

    # Extraer version numerica del nombre base si ya tiene sufijo _vN
    import re
    m = re.match(r"^(.*?)(_v(\d+))?$", base)
    stem = m.group(1) if m else base

    # Encontrar el primer numero disponible
    version_num = 1
    while True:
        candidate = f"{stem}_v{version_num}{ext}"
        if not os.path.exists(candidate):
            break
        version_num += 1

    os.makedirs(os.path.dirname(os.path.abspath(candidate)), exist_ok=True)
    with open(candidate, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    return candidate


# ---------------------------------------------------------------------------
# load_profile
# ---------------------------------------------------------------------------

def load_profile(path: str) -> dict:
    """
    Carga y valida minimamente un perfil desde JSON.
    Lanza ValueError si faltan secciones obligatorias.
    """
    with open(path, "r", encoding="utf-8") as f:
        profile = json.load(f)

    required = ["meta", "camara", "optica", "escala", "patron",
                "homografia", "puntos_crudos", "metricas", "checks"]
    missing = [k for k in required if k not in profile]
    if missing:
        raise ValueError(f"Perfil invalido: faltan secciones {missing} en {path}")

    H_list = profile["homografia"].get("H")
    if H_list is None:
        raise ValueError("Perfil invalido: 'homografia.H' no encontrado")

    return profile


# ---------------------------------------------------------------------------
# recompute_H
# ---------------------------------------------------------------------------

def recompute_H(profile: dict) -> np.ndarray:
    """
    Reproduce la homografia H desde los puntos_crudos almacenados en el perfil.
    KPI-4: trazabilidad — H debe ser reproducible desde los puntos originales.

    Retorna ndarray (3,3).
    Lanza RuntimeError si OpenCV no esta disponible o la deteccion falla.
    """
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError("recompute_H requiere opencv-python") from e

    pts = profile["puntos_crudos"]
    px_list  = pts["px"]
    mm_list  = pts["mm_nominal"]

    if len(px_list) < 4:
        raise ValueError(f"Se necesitan >= 4 puntos para recompute_H (hay {len(px_list)})")

    src = np.array(px_list,  dtype=np.float64)  # (N,2) en pixeles
    dst = np.array(mm_list,  dtype=np.float64)  # (N,2) en mm

    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 2.0)
    if H is None:
        raise RuntimeError("recompute_H: cv2.findHomography retorno None — puntos degenerados")

    return H


# ---------------------------------------------------------------------------
# helpers internos
# ---------------------------------------------------------------------------

def _require_ndarray(arr: Any, shape: tuple, name: str) -> None:
    if not isinstance(arr, np.ndarray):
        raise TypeError(f"{name} debe ser ndarray, no {type(arr).__name__}")
    if arr.shape != shape:
        raise ValueError(f"{name} debe tener shape {shape}, tiene {arr.shape}")


def _require_keys(d: Any, keys: List[str], name: str) -> None:
    if not isinstance(d, dict):
        raise TypeError(f"{name} debe ser dict")
    missing = [k for k in keys if k not in d]
    if missing:
        raise ValueError(f"{name} le faltan claves: {missing}")
