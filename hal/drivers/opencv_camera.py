# -*- coding: utf-8 -*-
"""hal/drivers/opencv_camera.py — Backend de cámara OpenCV (webcam USB)."""
from __future__ import annotations
import os
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
import cv2
from hal.base_camera import BaseCamera


class OpenCVCamera(BaseCamera):

    def __init__(self, index: int = 0):
        self.index = int(index)
        self._cap = None

    def open(self) -> None:
        if self._cap and self._cap.isOpened():
            return
        self._cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(self.index)
        if not self._cap.isOpened():
            raise RuntimeError("No se pudo abrir la cámara OpenCV index=%d" % self.index)

    def close(self) -> None:
        if self._cap:
            try: self._cap.release()
            except Exception: pass
        self._cap = None

    def read_frame_bgr(self):
        if not self._cap or not self._cap.isOpened():
            self.open()
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError("No se pudo leer frame (OpenCV index=%d)" % self.index)
        return frame

    def safe_shutdown(self) -> None:
        """Apagado seguro: detener la captura y cerrar. Ver BaseCamera."""
        try:
            self.stop_capture()
        except Exception:
            pass
        self.close()
