# -*- coding: utf-8 -*-
"""
hal/drivers/sim_camera.py — Cámara simulada para testing.

Puede cargar una imagen de calibración real (PNG) o generar patrón sintético.
Si se proporciona calibration_image_path, carga la imagen al abrir.
Si la imagen no existe o no se proporciona, genera patrón sintético como fallback.

Uso:
    # Con imagen de calibración
    cam = SimCamera(calibration_image_path="/path/to/tablero.png")
    cam.open()
    frame = cam.read_frame_bgr()  # ← retorna la imagen cargada

    # Sin imagen (patrón sintético)
    cam = SimCamera()
    frame = cam.read_frame_bgr()  # ← retorna patrón dinámico
"""
from __future__ import annotations
import time
import os
import numpy as np
import cv2
from hal.base_camera import BaseCamera


class SimCamera(BaseCamera):

    def __init__(self, width: int = 640, height: int = 480,
                 calibration_image_path: str | None = None):
        """
        Args:
            width, height: Dimensiones si se genera patrón sintético
            calibration_image_path: Ruta a PNG/JPG de calibración.
                Si existe, se carga y redimensiona a (height, width).
                Si no existe, se usa patrón sintético.
        """
        self.width = int(width)
        self.height = int(height)
        self.calibration_image_path = calibration_image_path
        self._calibration_frame = None  # Frame cargado (BGR, H×W×3 uint8)
        self._open = False
        self._frame_n = 0

    def open(self) -> None:
        self._open = True

        # Intenta cargar imagen de calibración si se especificó
        if self.calibration_image_path and os.path.exists(self.calibration_image_path):
            try:
                img = cv2.imread(self.calibration_image_path, cv2.IMREAD_COLOR)
                if img is not None and img.size > 0:
                    # Redimensionar a las dimensiones solicitadas
                    img_resized = cv2.resize(img, (self.width, self.height))
                    self._calibration_frame = img_resized
                    print("SimCamera: abierta con imagen de calibración (%d×%d)"
                          % (self.width, self.height))
                    return
            except Exception as e:
                print("SimCamera: advertencia — no se pudo cargar calibración: %s" % e)

        print("SimCamera: abierta con patrón sintético (%d×%d)" % (self.width, self.height))

    def close(self) -> None:
        self._open = False

    def read_frame_bgr(self):
        if not self._open:
            self.open()

        # Si tenemos imagen de calibración cargada, devolverla (con ruido mínimo para variación)
        if self._calibration_frame is not None:
            frame = self._calibration_frame.copy().astype(np.float32)
            # Agregar ruido Gaussiano mínimo (~1%) para simular variación natural
            noise = np.random.normal(0, 2.0, frame.shape)
            frame = frame + noise
            frame = np.clip(frame, 0, 255).astype(np.uint8)
            return frame

        # Fallback: patrón sintético
        self._frame_n += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        t = time.time()
        v = int((t % 2.0) / 2.0 * 200) + 55
        frame[:, :, 0] = v
        frame[:, :, 1] = (self._frame_n * 3) % 256
        frame[:, :, 2] = 128
        for i in range(0, self.width, 80):
            frame[:, i, :] = 200
        for j in range(0, self.height, 60):
            frame[j, :, :] = 200
        return frame

    def set_calibration_image(self, image_path: str | None) -> bool:
        """
        Cambia la imagen de calibración en tiempo de ejecución.
        Retorna True si se cargó exitosamente, False si no existe o hay error.
        """
        if image_path is None:
            self.calibration_image_path = None
            self._calibration_frame = None
            return True

        if not os.path.exists(image_path):
            print("SimCamera.set_calibration_image: archivo no existe: %s" % image_path)
            return False

        try:
            img = cv2.imread(image_path, cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                print("SimCamera.set_calibration_image: no se pudo leer imagen: %s" % image_path)
                return False

            img_resized = cv2.resize(img, (self.width, self.height))
            self.calibration_image_path = image_path
            self._calibration_frame = img_resized
            print("SimCamera.set_calibration_image: cargada %s" % image_path)
            return True
        except Exception as e:
            print("SimCamera.set_calibration_image: error: %s" % e)
            return False

    def safe_shutdown(self) -> None:
        """Apagado seguro: detener la captura y cerrar. Ver BaseCamera."""
        try:
            self.stop_capture()
        except Exception:
            pass
        self.close()
