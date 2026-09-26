# -*- coding: utf-8 -*-
"""
camera_control/calibration.py
===============================
Calibración espacial px → mm para microLIBS  (v1.0)

Método: Transformación afín completa estimada por movimiento del stage.
El stage se mueve a posiciones conocidas; se registra qué pixel corresponde
a cada posición. Con 3 pares (px, mm) se calcula la matriz afín 2×2 completa:

    [x_mm]   [a  b] [px]   [tx]
    [y_mm] = [c  d] [py] + [ty]

Donde la matriz [a b / c d] absorbe escala X, escala Y, rotación y cizallamiento.

La calibración se guarda en DOS lugares:
  - session_dir/calibration.json      → específica de la sesión (siempre)
  - calib_dir/calibration_<key>.json  → reutilizable entre sesiones (mismo hardware)

La clave de reutilización es: "<stage_driver>__<camera_label_sanitizado>"

Uso:
    cal = StageCalibration()
    cal.add_point(px=320, py=240, x_mm=0.0, y_mm=0.0)
    cal.add_point(px=640, py=240, x_mm=1.0, y_mm=0.0)
    cal.add_point(px=320, py=480, x_mm=0.0, y_mm=1.0)
    cal.fit()
    x_mm, y_mm = cal.px_to_mm(500, 300)

    cal.save_session(session_dir)
    cal.save_persistent(calib_dir, stage_driver="movi", camera_label="Webcam [1]")

    cal2 = StageCalibration.load(path)
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class CalibPoint:
    """Un par (pixel, mm) medido durante la calibración."""
    px: float
    py: float
    x_mm: float
    y_mm: float
    label: str = ""          # descripción opcional del punto


class StageCalibration:
    """
    Calibración afín completa entre coordenadas de imagen (px) y del stage (mm).

    Atributos públicos tras fit():
        A       : matriz 2×2  [[a, b], [c, d]]  (lista de listas)
        t       : traslación  [tx, ty]
        valid   : True si fit() tuvo éxito
        residual_mm : error RMS de los puntos de calibración
        n_points    : número de puntos usados
    """

    METHOD = "stage_referenced_affine_v1"

    def __init__(self):
        self.points: List[CalibPoint] = []
        self.A: Optional[List[List[float]]] = None   # 2×2
        self.t: Optional[List[float]] = None          # [tx, ty]
        self.valid: bool = False
        self.residual_mm: float = 0.0
        self.n_points: int = 0
        self.fitted_iso: str = ""
        self.stage_driver: str = ""
        self.camera_label: str = ""
        self.notes: str = ""

    # ------------------------------------------------------------------ puntos

    def add_point(self, px: float, py: float, x_mm: float, y_mm: float,
                  label: str = "") -> None:
        self.points.append(CalibPoint(px=px, py=py, x_mm=x_mm, y_mm=y_mm, label=label))
        self.valid = False   # requiere nuevo fit()

    def clear_points(self) -> None:
        self.points.clear()
        self.valid = False

    # ------------------------------------------------------------------ fit

    def fit(self) -> bool:
        """
        Calcula la transformación afín por mínimos cuadrados.
        Requiere al menos 3 puntos no colineales.
        Retorna True si el ajuste es válido.
        """
        n = len(self.points)
        if n < 3:
            self.valid = False
            self.notes = "fit: se necesitan >= 3 puntos (hay %d)" % n
            return False

        # Resolver por mínimos cuadrados:
        #   [x_mm_i]   [px_i  py_i  1  0    0    0 ] [a]
        #   [y_mm_i] = [0     0     0  px_i py_i  1 ] [b]
        #                                              [tx]
        #                                              [c]
        #                                              [d]
        #                                              [ty]
        try:
            import numpy as np
        except ImportError:
            self.valid = False
            self.notes = "fit: numpy no disponible"
            return False

        M_rows = []
        b_vec = []
        for p in self.points:
            M_rows.append([p.px, p.py, 1.0, 0.0, 0.0, 0.0])
            b_vec.append(p.x_mm)
            M_rows.append([0.0, 0.0, 0.0, p.px, p.py, 1.0])
            b_vec.append(p.y_mm)

        M = np.array(M_rows, dtype=float)
        b = np.array(b_vec, dtype=float)

        # lstsq resuelve min ||M·x - b||
        sol, residuals, rank, sv = np.linalg.lstsq(M, b, rcond=None)

        a, b_, tx, c, d, ty = sol.tolist()
        self.A  = [[a, b_], [c, d]]
        self.t  = [tx, ty]
        self.n_points = n

        # Error RMS
        errs = []
        for p in self.points:
            xp, yp = self._transform(p.px, p.py)
            errs.append((xp - p.x_mm)**2 + (yp - p.y_mm)**2)
        self.residual_mm = float(np.sqrt(np.mean(errs)))

        # Verificar que la solución es razonable (determinante ≠ 0)
        det = a * d - b_ * c
        if abs(det) < 1e-12:
            self.valid = False
            self.notes = "fit: matriz singular (puntos colineales o coincidentes)"
            return False

        self.valid = True
        self.fitted_iso = _now_iso()
        self.notes = "fit OK | n=%d | residual=%.4f mm | det=%.6f" % (n, self.residual_mm, det)
        return True

    # ------------------------------------------------------------------ transformación

    def _transform(self, px: float, py: float) -> Tuple[float, float]:
        """Aplica la transformación afín. No verifica valid."""
        a, b_ = self.A[0]
        c, d  = self.A[1]
        tx, ty = self.t
        x_mm = a * px + b_ * py + tx
        y_mm = c * px + d  * py + ty
        return x_mm, y_mm

    def px_to_mm(self, px: float, py: float) -> Tuple[float, float]:
        """
        Convierte coordenadas de imagen a mm del stage.
        Lanza RuntimeError si la calibración no es válida.
        """
        if not self.valid:
            raise RuntimeError(
                "Calibración no válida. Ejecutá la calibración primero."
            )
        return self._transform(px, py)

    def px_to_mm_safe(self, px: float, py: float) -> Optional[Tuple[float, float]]:
        """Como px_to_mm pero retorna None en lugar de lanzar excepción."""
        if not self.valid:
            return None
        return self._transform(px, py)

    # ------------------------------------------------------------------ propiedades derivadas

    def scale_x_mm_per_px(self) -> Optional[float]:
        """Escala aproximada en X (mm por pixel). None si no calibrado."""
        if not self.valid:
            return None
        import math
        a, b_ = self.A[0]
        return math.sqrt(a**2 + b_**2)

    def scale_y_mm_per_px(self) -> Optional[float]:
        if not self.valid:
            return None
        import math
        c, d = self.A[1]
        return math.sqrt(c**2 + d**2)

    def rotation_deg(self) -> Optional[float]:
        """Ángulo de rotación de la cámara respecto al stage (grados)."""
        if not self.valid:
            return None
        import math
        a, b_ = self.A[0]
        return math.degrees(math.atan2(b_, a))

    def looks_suspicious(self, max_rot_deg: float = 20.0,
                         max_scale_ratio: float = 2.5) -> tuple:
        """
        Detecta calibraciones probablemente incorrectas.

        Retorna (bool, str): (True, motivo) si la calibración parece mala,
        (False, "") si parece razonable.

        Criterios:
          - Rotación > max_rot_deg: el stage está muy inclinado respecto a la imagen.
            Para una cámara bien montada sobre el stage debería ser < 10-15°.
          - Ratio de escala X/Y > max_scale_ratio: las escalas en X e Y son muy
            diferentes, lo que suele indicar que los ejes se marcaron mal durante
            la calibración.

        Nota: con solo 3 puntos el residual siempre es 0 (sistema exactamente
        determinado), por lo que el residual no distingue calibraciones erróneas.
        """
        if not self.valid:
            return True, "Calibración no válida."
        import math
        rot = self.rotation_deg()
        sx  = self.scale_x_mm_per_px()
        sy  = self.scale_y_mm_per_px()
        reasons = []
        if rot is not None and abs(rot) > max_rot_deg:
            reasons.append(
                "Rotación %.1f° (límite: %.0f°). "
                "El stage parece inclinado respecto a la cámara. "
                "Recalibrá marcando los mismos puntos con más cuidado." % (rot, max_rot_deg))
        if sx and sy:
            ratio = max(sx, sy) / max(min(sx, sy), 1e-12)
            if ratio > max_scale_ratio:
                reasons.append(
                    "Relación de escala X/Y = %.1fx (límite: %.1fx). "
                    "Las escalas son muy asimétricas — probablemente los puntos "
                    "de calibración se marcaron en posiciones incorrectas." % (ratio, max_scale_ratio))
        if reasons:
            return True, " | ".join(reasons)
        return False, ""

    def summary(self) -> str:
        if not self.valid:
            return "Calibración no válida."
        sx = self.scale_x_mm_per_px()
        sy = self.scale_y_mm_per_px()
        rot = self.rotation_deg()
        return (
            "Calibración valida | n=%d puntos\n"
            "  Escala X: %.5f mm/px  (%.1f px/mm)\n"
            "  Escala Y: %.5f mm/px  (%.1f px/mm)\n"
            "  Rotación: %.2f deg\n"
            "  Residual RMS: %.4f mm"
        ) % (
            self.n_points,
            sx, 1.0/sx if sx else 0,
            sy, 1.0/sy if sy else 0,
            rot,
            self.residual_mm,
        )

    # ------------------------------------------------------------------ serialización

    def to_dict(self) -> dict:
        return {
            "method":        self.METHOD,
            "valid":         self.valid,
            "fitted_iso":    self.fitted_iso,
            "stage_driver":  self.stage_driver,
            "camera_label":  self.camera_label,
            "n_points":      self.n_points,
            "residual_mm":   self.residual_mm,
            "A":             self.A,
            "t":             self.t,
            "notes":         self.notes,
            "scale_x_mm_per_px": self.scale_x_mm_per_px(),
            "scale_y_mm_per_px": self.scale_y_mm_per_px(),
            "rotation_deg":      self.rotation_deg(),
            "points": [
                {"px": p.px, "py": p.py, "x_mm": p.x_mm, "y_mm": p.y_mm, "label": p.label}
                for p in self.points
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StageCalibration":
        cal = cls()
        cal.valid        = bool(d.get("valid", False))
        cal.fitted_iso   = d.get("fitted_iso", "")
        cal.stage_driver = d.get("stage_driver", "")
        cal.camera_label = d.get("camera_label", "")
        cal.n_points     = int(d.get("n_points", 0))
        cal.residual_mm  = float(d.get("residual_mm", 0.0))
        cal.A            = d.get("A")
        cal.t            = d.get("t")
        cal.notes        = d.get("notes", "")
        for p in d.get("points", []):
            cal.points.append(CalibPoint(
                px=p["px"], py=p["py"],
                x_mm=p["x_mm"], y_mm=p["y_mm"],
                label=p.get("label", ""),
            ))
        return cal

    # ------------------------------------------------------------------ I/O

    def save_session(self, session_dir: str) -> str:
        """Guarda calibration.json en la carpeta de sesión."""
        path = os.path.join(session_dir, "calibration.json")
        _write_json(path, self.to_dict())
        return path

    def save_persistent(self, calib_dir: str, stage_driver: str = "",
                        camera_label: str = "") -> str:
        """
        Guarda la calibración en una carpeta persistente reutilizable.
        El nombre de archivo codifica el hardware: stage + cámara.
        """
        os.makedirs(calib_dir, exist_ok=True)
        key = _make_key(stage_driver or self.stage_driver,
                        camera_label or self.camera_label)
        fname = "calibration_%s.json" % key
        path = os.path.join(calib_dir, fname)
        data = self.to_dict()
        data["stage_driver"]  = stage_driver or self.stage_driver
        data["camera_label"]  = camera_label or self.camera_label
        _write_json(path, data)
        return path

    @classmethod
    def load(cls, path: str) -> "StageCalibration":
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return cls.from_dict(d)

    @classmethod
    def load_persistent(cls, calib_dir: str, stage_driver: str,
                        camera_label: str) -> Optional["StageCalibration"]:
        """
        Busca y carga una calibración guardada para este hardware.
        Retorna None si no existe.
        """
        key = _make_key(stage_driver, camera_label)
        path = os.path.join(calib_dir, "calibration_%s.json" % key)
        if not os.path.isfile(path):
            return None
        try:
            return cls.load(path)
        except Exception:
            return None

    @classmethod
    def list_persistent(cls, calib_dir: str) -> List[dict]:
        """Lista todas las calibraciones guardadas en calib_dir."""
        if not os.path.isdir(calib_dir):
            return []
        result = []
        for fname in os.listdir(calib_dir):
            if fname.startswith("calibration_") and fname.endswith(".json"):
                path = os.path.join(calib_dir, fname)
                try:
                    with open(path, encoding="utf-8") as f:
                        d = json.load(f)
                    result.append({
                        "path": path,
                        "stage_driver": d.get("stage_driver", ""),
                        "camera_label": d.get("camera_label", ""),
                        "fitted_iso":   d.get("fitted_iso", ""),
                        "valid":        d.get("valid", False),
                        "residual_mm":  d.get("residual_mm", 0.0),
                    })
                except Exception:
                    pass
        return result


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _make_key(stage_driver: str, camera_label: str) -> str:
    """Genera una clave de archivo segura para el par stage+cámara."""
    def _clean(s):
        s = s.lower().strip()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        return s[:40].strip("_")
    return "%s__%s" % (_clean(stage_driver), _clean(camera_label))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ===========================================================================
# Cal-A — Calibracion homografica estatica (tablero de ajedrez)
# ===========================================================================
# Todas las funciones de esta seccion son PURAS respecto al hardware:
# reciben arrays numpy / dicts y retornan resultados o lanzan excepciones
# visibles. La UI y el wizard capturan las excepciones; nunca las silencian.


def to_gray(img: "np.ndarray") -> "np.ndarray":
    """
    Convierte cualquier imagen numpy a gris 1-canal uint8.

    Canales soportados:
      ndim=2                  ya es gris — solo normalizar profundidad
      ndim=3, shape[2]=1      quitar dimension extra
      ndim=3, shape[2]=2      tomar canal 0  (YA, Bayer+mask, o cualquier 2-canal)
      ndim=3, shape[2]=3      BGR -> GRAY  (OpenCV)
      ndim=3, shape[2]=4      BGRA -> GRAY (OpenCV)
      ndim=3, shape[2]>4      tomar canal 0

    Profundidad soportada:
      uint8   sin cambio
      uint16  >> 8  (toma el byte alto; preserva contraste relativo)
      float   normalizar al rango 0..255

    Nunca lanza excepcion: si el formato es desconocido devuelve canal 0 uint8.
    """
    import numpy as np

    # ── 1. Normalizar profundidad a uint8 ────────────────────────────────────
    if img.dtype == np.uint16:
        img = (img >> 8).astype(np.uint8)
    elif img.dtype != np.uint8:
        mn, mx = float(img.min()), float(img.max())
        span = mx - mn if mx > mn else 1.0
        img = ((img.astype(np.float32) - mn) / span * 255.0).astype(np.uint8)

    # ── 2. Reducir a 1 canal ─────────────────────────────────────────────────
    if img.ndim == 2:
        return img

    n = img.shape[2]
    if n == 1:
        return img[:, :, 0]
    if n == 2:
        # Canal 0 = luminancia en YA, plano de datos en Bayer+máscara, etc.
        return img[:, :, 0]
    if n == 3:
        try:
            import cv2 as _cv2
            return _cv2.cvtColor(img, _cv2.COLOR_BGR2GRAY)
        except Exception:
            return img[:, :, 0]
    if n == 4:
        try:
            import cv2 as _cv2
            return _cv2.cvtColor(img, _cv2.COLOR_BGRA2GRAY)
        except Exception:
            # Descartar alpha y convertir los 3 primeros canales
            return img[:, :, 0]
    # Fallback para cualquier otro numero de canales
    return img[:, :, 0]


def load_dead_pixel_mask(
    shape: tuple,
    columns: list,
    cluster_bbox: Optional[tuple],
) -> "np.ndarray":
    """
    Construye una mascara booleana de pixeles defectuosos.

    shape        : (alto, ancho) de la imagen
    columns      : lista de indices de columna quemadas (toda la columna = True)
    cluster_bbox : (y0, x0, y1, x1) del cumulo de pixeles muertos, o None

    True  = pixel muerto (ignorar)
    False = pixel valido
    """
    import numpy as np

    mask = np.zeros(shape, dtype=bool)
    for col in columns:
        mask[:, col] = True
    if cluster_bbox is not None:
        y0, x0, y1, x1 = cluster_bbox
        mask[y0:y1, x0:x1] = True
    return mask


def sharpness_score(
    img: "np.ndarray",
    mask: "Optional[np.ndarray]" = None,
) -> float:
    """
    Varianza del Laplaciano sobre pixeles validos.

    Valores tipicos:
        > 200  : imagen muy nitida
        50–200 : aceptable para calibracion
        < 50   : probable desenfoque -> rechazar

    img  : array uint8 o float, monocromatico o RGB (se convierte a gris)
    mask : bool ndarray (H,W), True = pixel muerto/excluir.
           Los pixeles muertos Y sus vecinos inmediatos (dilatacion 3×3)
           se excluyen del calculo para no inflar la varianza con
           discontinuidades artificiales en el borde de los defectos.
           Si mask es None, se usan todos los pixeles (comportamiento anterior).
    """
    import numpy as np

    gray = to_gray(img)
    try:
        import cv2
        lap = cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F)
    except ImportError:
        from scipy.ndimage import laplace
        lap = laplace(gray.astype(float)).astype("float32")

    if mask is not None:
        m = mask[:lap.shape[0], :lap.shape[1]]
        if m.any():
            try:
                import cv2 as _cv2
                # Dilatar 1 px: excluir tambien vecinos cuyo Laplaciano esta
                # contaminado por la discontinuidad en el borde del defecto
                dead_dil = _cv2.dilate(
                    m.astype(np.uint8), np.ones((3, 3), np.uint8)
                ).astype(bool)
            except ImportError:
                dead_dil = m
            valid = ~dead_dil
            if valid.any():
                return float(np.var(lap[valid]))
            return 0.0

    return float(np.var(lap))


def check_exposure(
    img: "np.ndarray",
    mask: "Optional[np.ndarray]" = None,
    sat_threshold: int = 250,
    dark_threshold: int = 5,
    max_sat_frac: float = 0.02,
    max_dark_frac: float = 0.10,
) -> dict:
    """
    Verifica que la exposicion de la imagen es adecuada para calibracion.

    mask : bool ndarray (H,W), True = pixel muerto/excluir.
           Los pixeles enmascarados se excluyen del calculo de fracciones
           para que columnas quemadas o el cumulo no distorsionen el resultado.

    Retorna:
        {"ok": bool, "saturated_frac": float, "underexposed_frac": float}
    """
    import numpy as np

    arr = to_gray(img).astype(np.float32)

    if mask is not None:
        m = mask[:arr.shape[0], :arr.shape[1]]
        valid = ~m
        vals = arr[valid] if valid.any() else arr.ravel()
    else:
        vals = arr.ravel()

    total     = vals.size
    sat_frac  = float(np.sum(vals >= sat_threshold) / total)
    dark_frac = float(np.sum(vals <= dark_threshold) / total)

    ok = (sat_frac <= max_sat_frac) and (dark_frac <= max_dark_frac)
    return {"ok": ok, "saturated_frac": sat_frac, "underexposed_frac": dark_frac}


def orientation_sign_check(
    move_mm: float,
    delta_px_observed: float,
    expected_axis: str,
) -> bool:
    """
    Poka-yoke de orientacion: verifica que el signo del desplazamiento en pixeles
    coincide con el signo del movimiento del stage en mm.

    move_mm            : desplazamiento comandado (+ o -)
    delta_px_observed  : cambio observado en la coordenada de imagen (+ o -)
    expected_axis      : "x" o "y" (informativo, no usado en la logica actual)

    Retorna True si los signos coinciden (sin importar magnitud).
    """
    if move_mm == 0.0 or delta_px_observed == 0.0:
        raise ValueError("orientation_sign_check: move_mm y delta_px_observed no pueden ser 0")
    return (move_mm > 0) == (delta_px_observed > 0)


def detect_chessboard(
    img: "np.ndarray",
    mask: "np.ndarray",
    inner_corners: tuple = (8, 6),
) -> "Optional[np.ndarray]":
    """
    Detecta las esquinas interiores de un tablero de ajedrez.
    API publica sin cambios — delega a detect_chessboard_ex.
    Retorna ndarray (N,2) float64 o None si falla.
    RuntimeError si demasiadas esquinas caen en pixeles muertos.
    """
    corners, _dbg, _msg = detect_chessboard_ex(img, mask, inner_corners)
    return corners


def detect_chessboard_ex(
    img: "np.ndarray",
    mask: "Optional[np.ndarray]",
    inner_corners: tuple = (8, 6),
) -> "tuple":
    """
    Version extendida de detect_chessboard.

    Preprocesamiento:
      Aplica CLAHE (clipLimit=2, tile 8x8) para estirar histogramas estrechos
      (ej. sigma~12 tipico de la Celestron con iluminacion uniforme).

    Cascada de deteccion — cada metodo se prueba primero sobre la imagen
    realzada (CLAHE) y luego sobre la original; se usa el primer exito:
      1. findChessboardCornersSB + NORMALIZE_IMAGE + EXHAUSTIVE
         (sub-pixel nativo, robusto a desenfoque y vineteo)
      2. findChessboardCornersSB + EXHAUSTIVE
         (fallback si NORMALIZE_IMAGE no esta disponible en esta version de OpenCV)
      3. findChessboardCorners clasico + ADAPTIVE_THRESH + NORMALIZE_IMAGE + cornerSubPix
         (fallback para OpenCV < 4.1 o cuando SB falla)

    Retorna (corners, debug_bgr, diag_msg) donde:
      corners   : ndarray (N,2) float64  o  None si no se detecto
      debug_bgr : imagen de lo que recibio el detector + esquinas dibujadas
      diag_msg  : str de diagnostico (patron, metodo, resultado)

    RuntimeError si >10% de esquinas caen en zona de pixeles muertos.
    """
    import cv2
    import numpy as np

    gray      = to_gray(img)
    pattern   = (inner_corners[0], inner_corners[1])
    n_expected = inner_corners[0] * inner_corners[1]

    # ── Realce de contraste: CLAHE ───────────────────────────────────────────
    # Para histogramas concentrados en grises medios (sigma ~12) el realce
    # es critico: multiplica el contraste local sin saturar globalmente.
    try:
        clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_enh = clahe.apply(gray)
    except Exception:
        gray_enh = gray   # fallback si CLAHE no esta disponible

    # ── Cascada de deteccion ─────────────────────────────────────────────────
    # Cada metodo se intenta primero sobre gray_enh (CLAHE), luego sobre gray.
    corners      = None
    method_used  = "ninguno"
    gray_used    = gray_enh    # imagen que finalmente recibio el detector

    _SUBPIX_CRITERIA = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    for g, lbl in ((gray_enh, "CLAHE"), (gray, "orig")):
        if corners is not None:
            break

        # Metodo A: SB + NORMALIZE_IMAGE + EXHAUSTIVE
        try:
            ret, raw = cv2.findChessboardCornersSB(
                g, pattern, cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE)
            if ret:
                corners = raw.reshape(-1, 2).astype(np.float64)
                method_used = f"SB+NORM+{lbl}"
                gray_used = g
                break
        except (cv2.error, AttributeError):
            pass

        # Metodo B: SB + EXHAUSTIVE (si NORMALIZE_IMAGE no soportado)
        try:
            ret, raw = cv2.findChessboardCornersSB(g, pattern, cv2.CALIB_CB_EXHAUSTIVE)
            if ret:
                corners = raw.reshape(-1, 2).astype(np.float64)
                method_used = f"SB+EXHAUST+{lbl}"
                gray_used = g
                break
        except (cv2.error, AttributeError):
            pass

        # Metodo C: clasico + ADAPTIVE_THRESH + NORMALIZE_IMAGE + cornerSubPix
        ret, raw = cv2.findChessboardCorners(
            g, pattern,
            cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if ret:
            raw = cv2.cornerSubPix(g, raw, (11, 11), (-1, -1), _SUBPIX_CRITERIA)
            corners = raw.reshape(-1, 2).astype(np.float64)
            method_used = f"clasico+subpix+{lbl}"
            gray_used = g
            break

    diag_msg = (
        f"patron={inner_corners[0]}x{inner_corners[1]} ({n_expected} esq.)  "
        f"metodo={method_used}  "
        f"resultado={'OK '+str(len(corners))+' esq.' if corners is not None else 'FALLO'}"
    )

    # ── Imagen de debug ──────────────────────────────────────────────────────
    # Muestra lo que recibio el detector (imagen realzada si CLAHE ayudo).
    debug_bgr = cv2.cvtColor(gray_used, cv2.COLOR_GRAY2BGR)
    if corners is not None:
        cv2.drawChessboardCorners(
            debug_bgr, pattern,
            corners.reshape(-1, 1, 2).astype(np.float32), True)
        cv2.putText(debug_bgr,
                    f"{len(corners)}/{n_expected} [{method_used}]",
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 80), 1)
    else:
        cv2.putText(debug_bgr, "NO DETECTADO", (8, 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 50, 220), 2)
        cv2.putText(debug_bgr, f"patron={inner_corners[0]}x{inner_corners[1]}",
                    (8, 64), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 100, 220), 1)

    if corners is None:
        return None, debug_bgr, diag_msg

    # ── Filtro de pixeles muertos ────────────────────────────────────────────
    if mask is not None:
        dead_count = 0
        for pt in corners:
            u = max(0, min(int(round(pt[0])), mask.shape[1] - 1))
            v = max(0, min(int(round(pt[1])), mask.shape[0] - 1))
            if mask[v, u]:
                dead_count += 1
        if dead_count > 0.10 * len(corners):
            raise RuntimeError(
                f"detect_chessboard: {dead_count}/{len(corners)} esquinas en pixeles muertos. "
                "Revisa la mascara o la posicion del tablero."
            )

    return corners, debug_bgr, diag_msg


def suggest_board_sizes(
    img: "np.ndarray",
    mask: "Optional[np.ndarray]",
    candidates: "Optional[list]" = None,
) -> "list":
    """
    Prueba varios patrones de tablero y retorna los que detectan esquinas.

    candidates : lista de (cols, rows); si None usa patrones comunes.
    Retorna lista de dicts {"inner": (c,r), "n_corners": int, "method": str}.
    """
    if candidates is None:
        candidates = [(8,6),(7,5),(9,6),(6,4),(5,4),(9,7),(7,7),(6,6),(10,7)]

    found = []
    for size in candidates:
        try:
            corners, _dbg, msg = detect_chessboard_ex(img, mask, inner_corners=size)
            if corners is not None:
                found.append({
                    "inner":    size,
                    "n_corners": len(corners),
                    "method":   msg.split("metodo=")[-1].split(" ")[0],
                })
        except RuntimeError:
            pass   # pixeles muertos — no sugiere ese tamaño
    return found


def image_diagnostics(
    img: "np.ndarray",
    mask: "Optional[np.ndarray]" = None,
) -> "dict":
    """
    Resumen diagnostico de la imagen: resolucion, sharpness, histograma.
    Excluye pixeles enmascarados del histograma si mask es provisto.
    """
    import numpy as np

    H, W = img.shape[:2]
    gray = to_gray(img)

    if mask is not None:
        m = mask[:H, :W]
        vals = gray[~m] if (~m).any() else gray.ravel()
    else:
        vals = gray.ravel()

    vals = vals.astype(np.float32)
    dark   = float((vals <  30).sum() / vals.size)
    bright = float((vals > 220).sum() / vals.size)
    mid    = 1.0 - dark - bright

    return {
        "resolucion":   (W, H),
        "n_canales":    img.ndim,
        "sharpness":    sharpness_score(gray, mask),
        "pmin":         int(vals.min()),
        "pmax":         int(vals.max()),
        "pmean":        float(vals.mean()),
        "pstd":         float(vals.std()),
        "pct_dark":     dark,
        "pct_mid":      mid,
        "pct_bright":   bright,
    }


def compute_homography(
    corners_px: "np.ndarray",
    corners_mm_nominal: "np.ndarray",
) -> "tuple":
    """
    Calcula la homografia H que mapea pixeles a mm.

    corners_px          : (N,2) coordenadas de esquinas en pixeles
    corners_mm_nominal  : (N,2) coordenadas nominales en mm (patron fisico)

    Retorna (H, metrics) donde:
        H       : ndarray (3,3) homografia px -> mm
        metrics : dict con rms_px, rms_um, det_lineal, isotropia_xy, esquinas_detectadas
    """
    import cv2
    import numpy as np

    if len(corners_px) < 4:
        raise ValueError(
            f"compute_homography requiere >= 4 puntos, recibio {len(corners_px)}"
        )
    if corners_px.shape != corners_mm_nominal.shape:
        raise ValueError(
            f"corners_px {corners_px.shape} y corners_mm_nominal {corners_mm_nominal.shape} "
            "deben tener el mismo shape"
        )

    src = corners_px.astype(np.float64)
    dst = corners_mm_nominal.astype(np.float64)

    H, _ = cv2.findHomography(src, dst, 0)   # 0 = sin RANSAC (todos los puntos)
    if H is None:
        raise RuntimeError("compute_homography: cv2.findHomography retorno None")

    # Error RMS
    src_h = np.hstack([src, np.ones((len(src), 1))])      # (N,3)
    proj  = (H @ src_h.T).T                               # (N,3)
    proj  = proj[:, :2] / proj[:, 2:3]                    # (N,2) en mm
    diff  = proj - dst
    rms_mm = float(np.sqrt(np.mean(diff ** 2)))
    rms_px = float(rms_mm * _px_per_mm_from_H(H))
    rms_um = rms_mm * 1000.0

    # Determinante del bloque lineal 2x2 (signo indica orientacion)
    det_lineal = float(H[0, 0] * H[1, 1] - H[0, 1] * H[1, 0])

    # Isotropia: ratio de escalas X / Y
    scale_x = float(np.sqrt(H[0, 0] ** 2 + H[1, 0] ** 2))
    scale_y = float(np.sqrt(H[0, 1] ** 2 + H[1, 1] ** 2))
    isotropia_xy = float(scale_x / scale_y) if scale_y > 1e-12 else float("inf")

    metrics = {
        "rms_px":              rms_px,
        "rms_um":              rms_um,
        "det_lineal":          det_lineal,
        "isotropia_xy":        isotropia_xy,
        "esquinas_detectadas": int(len(corners_px)),
    }
    return H, metrics


def _px_per_mm_from_H(H: "np.ndarray") -> float:
    """Escala aproximada en px/mm extraida del bloque lineal de H."""
    import numpy as np
    scale_mm_per_px = float(np.sqrt(abs(H[0, 0]) ** 2 + abs(H[1, 0]) ** 2))
    if scale_mm_per_px < 1e-12:
        return 0.0
    return 1.0 / scale_mm_per_px


def validate_calibration(
    metrics: dict,
    H: "np.ndarray",
    *,
    rms_um_max: float = 30.0,
    min_corners: int = 40,
    scale_px_per_mm_ref: float = 218.0,
    scale_tol_frac: float = 0.15,
) -> dict:
    """
    Aplica poka-yokes a los resultados de calibracion.

    Criterios:
        rms_ok       : rms_um <= rms_um_max
        corners_ok   : esquinas_detectadas >= min_corners
        espejado_ok  : det_lineal > 0 (no espejado)
        escala_cross_ok : escala derivada de H dentro de +/-scale_tol_frac de scale_px_per_mm_ref

    Retorna:
        {"passed": bool, "checks": {nombre: bool, ...}, "detail": {nombre: valor, ...}}
    """
    import numpy as np

    rms_um    = float(metrics.get("rms_um", float("inf")))
    n_corners = int(metrics.get("esquinas_detectadas", 0))
    det       = float(metrics.get("det_lineal", 0.0))

    rms_ok      = rms_um <= rms_um_max
    corners_ok  = n_corners >= min_corners
    espejado_ok = det > 0

    # Cross-check de escala: px/mm derivado de H vs referencia hardware
    scale_from_H = _px_per_mm_from_H(H)
    if scale_px_per_mm_ref > 0 and scale_from_H > 0:
        ratio = scale_from_H / scale_px_per_mm_ref
        escala_cross_ok = abs(ratio - 1.0) <= scale_tol_frac
    else:
        escala_cross_ok = False

    checks = {
        "rms_ok":         rms_ok,
        "corners_ok":     corners_ok,
        "espejado_ok":    espejado_ok,
        "escala_cross_ok": escala_cross_ok,
    }
    passed = all(checks.values())

    detail = {
        "rms_um":              rms_um,
        "esquinas_detectadas": n_corners,
        "det_lineal":          det,
        "scale_from_H_px_per_mm": scale_from_H,
        "scale_ref_px_per_mm":    scale_px_per_mm_ref,
    }

    return {"passed": passed, "checks": checks, "detail": detail}
