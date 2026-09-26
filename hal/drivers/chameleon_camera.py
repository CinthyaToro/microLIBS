# -*- coding: utf-8 -*-
"""hal/drivers/chameleon_camera.py — Backend FLIR Chameleon via pyflycap2."""
from __future__ import annotations
import logging
import os
import time
from typing import List, Optional, Tuple
from hal.base_camera import BaseCamera

log = logging.getLogger(__name__)


class ChameleonCamera(BaseCamera):

    DEFAULT_CANDIDATES = [
        (1280, 960, "y8", 7.5),
        (1280, 960, "y8", 15.0),
        (800,  600, "y8", 15.0),
        (640,  480, "y8", 15.0),
    ]

    def __init__(self, serial: int,
                 dll_dir: str = r"C:\Program Files\Point Grey Research\FlyCap2 Viewer\bin64",
                 warmup_frames: int = 10,
                 candidates: Optional[List[Tuple]] = None,
                 defect_map_path: Optional[str] = None,
                 require_defect_map: bool = False):
        self.serial = int(serial)
        self.dll_dir = dll_dir
        self.warmup_frames = int(warmup_frames)
        self.candidates = candidates or self.DEFAULT_CANDIDATES
        self._defect_map_path = defect_map_path
        self._require_defect_map = require_defect_map
        self._corrector = None
        self._cam = None
        self._capturing = False

    @property
    def needs_streaming(self) -> bool:
        return True

    def _ensure_import(self):
        os.environ["PATH"] = self.dll_dir + os.pathsep + os.environ.get("PATH", "")
        from pyflycap2.interface import Camera
        return Camera

    def open(self) -> None:
        if self._cam is not None:
            return
        Camera = self._ensure_import()
        self._cam = Camera(serial=self.serial, context_type="IIDC")
        self._cam.connect()
        self._set_best_mode()
        self._load_corrector()

    def _load_corrector(self) -> None:
        if self._defect_map_path is None:
            if self._require_defect_map:
                raise RuntimeError(
                    "ChameleonCamera serial=%s requiere mapa de defectos "
                    "pero no se proporcionó ninguno (serie de producción conocida). "
                    "Verificá que calibration/chameleon_%s_defectmap.json existe "
                    "en la raíz del proyecto." % (self.serial, self.serial)
                )
            log.warning(
                "ChameleonCamera serial=%s abierta SIN mapa de defectos — "
                "los píxeles defectuosos del sensor no serán corregidos.",
                self.serial,
            )
            return
        from hal.defect_correction import DefectCorrector
        self._corrector = DefectCorrector.load(
            self._defect_map_path, camera_serial=self.serial
        )
        log.info("Mapa de defectos cargado: %s", self._defect_map_path)

    def close(self) -> None:
        try: self.stop_capture()
        except Exception: pass
        if self._cam is not None:
            try: self._cam.disconnect()
            except Exception: pass
        self._cam = None

    def _set_best_mode(self) -> None:
        for w, h, fmt, rate in self.candidates:
            try:
                if self._cam.check_video_mode(w, h, fmt, rate):
                    self._cam.set_video_mode(w, h, fmt, rate)
                    return
            except Exception:
                continue

    def start_capture(self) -> None:
        if self._cam is None:
            self.open()
        if self._capturing:
            return
        self._cam.start_capture()
        self._capturing = True
        ok = 0; tries = 0
        while ok < self.warmup_frames and tries < self.warmup_frames * 3:
            tries += 1
            try: self._cam.read_next_image(); ok += 1
            except Exception: time.sleep(0.01)

    def stop_capture(self) -> None:
        if self._cam is None or not self._capturing:
            return
        try: self._cam.stop_capture()
        except Exception: pass
        self._capturing = False

    def _read_image_dict(self) -> dict:
        if self._cam is None: self.open()
        if not self._capturing: self.start_capture()
        err41 = 0
        while True:
            try:
                self._cam.read_next_image()
                img = self._cam.get_current_image()
                if not isinstance(img, dict) or "buffer" not in img:
                    raise RuntimeError("get_current_image() inesperado")
                return img
            except Exception as e:
                msg = str(e).lower()
                if "consistency" in msg or "code: 41" in msg:
                    err41 += 1
                    if err41 >= 10:
                        self.stop_capture(); time.sleep(0.2); self.start_capture(); err41 = 0
                    continue
                raise

    @staticmethod
    def _decode_gray(img: dict):
        import numpy as np
        h, w, stride = int(img["rows"]), int(img["cols"]), int(img["stride"])
        pix = img.get("pix_fmt", "unknown")
        buf = img["buffer"]
        if pix == "y16":
            arr = np.frombuffer(buf, dtype=np.uint16)
            stride_px = stride // 2
            if arr.size >= h * stride_px:
                f16 = arr[:h*stride_px].reshape((h, stride_px))[:, :w]
            else:
                f16 = arr[:h*w].reshape((h, w))
            return (f16 / 256).astype("uint8"), pix
        arr = np.frombuffer(buf, dtype=np.uint8)
        if arr.size >= h * stride:
            f = arr[:h*stride].reshape((h, stride))[:, :w]
        else:
            f = arr[:h*w].reshape((h, w))
        return f, pix

    def read_frame_bgr(self):
        import cv2
        img = self._read_image_dict()
        gray, _ = self._decode_gray(img)
        if self._corrector is not None:
            gray = self._corrector.apply(gray)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def safe_shutdown(self) -> None:
        """Apagado seguro: detener la captura y cerrar. Ver BaseCamera."""
        try:
            self.stop_capture()
        except Exception:
            pass
        self.close()
