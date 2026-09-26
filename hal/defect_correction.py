# -*- coding: utf-8 -*-
"""hal/defect_correction.py — Corrección de píxeles defectuosos de sensor."""
from __future__ import annotations
import json
import logging
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


class DefectCorrector:
    """Aplica un mapa de defectos fijos de sensor a una imagen cruda (uint8, mono).

    Carga el JSON con `load()` y llama a `apply(gray)` antes de cualquier
    filtro o recorte. Siempre opera sobre el sensor completo.
    """

    def __init__(self, ref_w: int, ref_h: int, camera_serial: str,
                 columns: list, clusters: list) -> None:
        self._ref_w = ref_w
        self._ref_h = ref_h
        self._camera_serial = str(camera_serial)
        self._columns = columns
        self._clusters = clusters

    @classmethod
    def load(cls, path, camera_serial: Optional[int] = None) -> "DefectCorrector":
        """Carga un mapa de defectos desde un JSON.

        camera_serial: si se pasa, valida contra el serial del JSON.
        Lanza ValueError si no coinciden.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        json_serial = str(data["camera_serial"])
        if camera_serial is not None:
            if str(int(camera_serial)) != json_serial:
                raise ValueError(
                    "Mapa de defectos incompatible: serial del mapa=%s, "
                    "serial de la cámara=%s" % (json_serial, camera_serial)
                )

        ref = data["reference_dims"]
        interp = data["interpolate"]
        return cls(
            ref_w=int(ref["width"]),
            ref_h=int(ref["height"]),
            camera_serial=json_serial,
            columns=interp["columns"],
            clusters=interp["clusters"],
        )

    def apply(self, gray: np.ndarray) -> np.ndarray:
        """Devuelve una copia corregida. No muta la entrada.

        Verifica dimensiones antes de operar; lanza ValueError si no coinciden.
        """
        h, w = gray.shape[:2]
        if h != self._ref_h or w != self._ref_w:
            raise ValueError(
                "Dimensiones incorrectas: se esperaba %dx%d (WxH), "
                "se recibió %dx%d" % (self._ref_w, self._ref_h, w, h)
            )

        out = gray.copy()

        # --- Corrección de columnas ----------------------------------------
        # Los vecinos buenos se leen del array ORIGINAL (gray) para que ninguna
        # columna del rango contamine a otra del mismo rango.
        for col in self._columns:
            xs, xe = int(col["x_start"]), int(col["x_end"])
            ys, ye = int(col["y_start"]), int(col["y_end"])
            left  = xs - 1 if xs > 0 else None
            right = xe + 1 if xe < w - 1 else None
            rows  = slice(ys, ye + 1)

            if left is not None and right is not None:
                vals = np.median(
                    np.stack([gray[rows, left], gray[rows, right]], axis=1),
                    axis=1,
                ).astype(np.uint8)
            elif left is not None:
                vals = gray[rows, left].copy()
            elif right is not None:
                vals = gray[rows, right].copy()
            else:
                continue

            out[rows, xs : xe + 1] = vals[:, np.newaxis]

        # --- Corrección de clusters ----------------------------------------
        ys_g, xs_g = np.mgrid[0:h, 0:w]
        for clust in self._clusters:
            cx     = int(clust["cx"])
            cy     = int(clust["cy"])
            radius = float(clust["radius"])

            dist        = np.sqrt((xs_g - cx) ** 2 + (ys_g - cy) ** 2)
            defect_mask = dist <= radius
            ring_mask   = (dist > radius) & (dist <= radius + 2)

            ring_pixels = gray[ring_mask]
            if ring_pixels.size == 0:
                continue

            median_val = int(np.median(ring_pixels))
            # Se aplica un único valor de mediana a todo el cluster. En bordes de
            # muestra puede dejar un parche plano visible; si resulta problemático,
            # reemplazar por interpolación pixel a pixel desde el anillo.
            out[defect_mask] = median_val

        return out
