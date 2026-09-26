# -*- coding: utf-8 -*-
"""
service/vision_service.py
==========================
Servicio de visión: gestión de la cámara activa y capturas programáticas.

- Enumera cámaras (OpenCV + Chameleon).
- Abre/cierra backends de hal/drivers/.
- Provee request_capture() para capturas desde ScanRunner.
- Mantiene _preview_state (escrito por presentation/preview_panel.py).
- open_preview_tk(): shim de compatibilidad que delega a presentation/.
  (permite que step0_wizard.py siga funcionando sin cambios)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Union

import cv2
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
try:
    if hasattr(cv2, "utils") and hasattr(cv2.utils, "logging"):
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    pass


@dataclass
class CameraDescriptor:
    """Descriptor de una cámara disponible."""
    kind: str            # "opencv" | "chameleon" | "sim_camera"
    label: str
    id: Union[int, str]  # index(int) | serial(int) | "sim"


def safe_write_json(path: str, data: dict) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def safe_imwrite(path: str, frame_bgr, ext: str, jpg_quality: int = 95) -> None:
    """Escritura robusta para rutas unicode/red."""
    ext = (ext or "png").lower().lstrip(".")
    if ext in ("jpg", "jpeg"):
        ok, buf = cv2.imencode(".jpg", frame_bgr,
                               [int(cv2.IMWRITE_JPEG_QUALITY), int(jpg_quality)])
    elif ext == "png":
        ok, buf = cv2.imencode(".png", frame_bgr)
    elif ext in ("tif", "tiff"):
        ok, buf = cv2.imencode(".tiff", frame_bgr)
    else:
        ok, buf = cv2.imencode("." + ext, frame_bgr)
    if not ok:
        raise RuntimeError("cv2.imencode falló (ext=%s)" % ext)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "wb") as f:
        f.write(buf.tobytes())


class VisionService:
    """
    Servicio de visión — único punto de acceso a la cámara.

    Uso básico:
        svc = VisionService()
        descs = svc.list_cameras()
        svc.set_selected(descs[0])
        frame = svc.read_frame_bgr()
        out = svc.request_capture(save_dir, base_name, kind="pre")
        svc.close()
    """

    def __init__(
        self,
        dll_dir: str = r"C:\Program Files\Point Grey Research\FlyCap2 Viewer\bin64",
        opencv_scan_max: int = 10,
        opencv_stop_after_misses: int = 4,
    ):
        self.dll_dir = dll_dir
        self.opencv_scan_max = int(opencv_scan_max)
        self.opencv_stop_after_misses = int(opencv_stop_after_misses)
        self.photo_format = "png"
        self.photo_quality = 95
        self.selected: Optional[CameraDescriptor] = None
        self._backend = None
        self._backend_kind: Optional[str] = None
        # Escrito por presentation/preview_panel.py; leído por request_capture()
        self._preview_state: Optional[dict] = None

    # ──────────────────────────────────────────── enumeración

    def list_cameras(self) -> List[CameraDescriptor]:
        cams: List[CameraDescriptor] = []
        cams.extend(self._list_opencv())
        cams.extend(self._list_chameleon())
        return cams

    @staticmethod
    def _get_opencv_device_names() -> dict:
        try:
            from pygrabber.dshow_graph import FilterGraph
            graph = FilterGraph()
            devices = graph.get_input_devices()
            return {i: name for i, name in enumerate(devices)}
        except Exception:
            pass
        try:
            import wmi
            c = wmi.WMI()
            names = {}
            for i, cam in enumerate(c.Win32_PnPEntity(PNPClass="Camera")):
                names[i] = getattr(cam, "Name", "Cámara %d" % i)
            if names:
                return names
        except Exception:
            pass
        return {}

    def _list_opencv(self) -> List[CameraDescriptor]:
        device_names = self._get_opencv_device_names()
        out = []
        misses = 0
        for i in range(self.opencv_scan_max):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(i)
            if cap.isOpened():
                name = device_names.get(i, "")
                label = ("Webcam [%d] %s" % (i, name)).strip() if name else (
                    "Webcam [index %d]" % i)
                out.append(CameraDescriptor(kind="opencv", label=label, id=i))
                misses = 0
                cap.release()
            else:
                misses += 1
                try: cap.release()
                except Exception: pass
                if misses >= self.opencv_stop_after_misses:
                    break
        return out

    def _list_chameleon(self) -> List[CameraDescriptor]:
        out = []
        try:
            os.environ["PATH"] = self.dll_dir + os.pathsep + os.environ.get("PATH", "")
            from pyflycap2.interface import CameraContext, Camera
        except Exception:
            return out
        try:
            cc = CameraContext(context_type="IIDC")
            cc.rescan_bus()
            n = cc.get_num_cameras()
        except Exception:
            return out
        for idx in range(n):
            try:
                cam = Camera(index=idx, context_type="IIDC")
                cam.connect()
                serial = int(cam.serial)
                itype = str(cam.interface_type)
                cam.disconnect()
                out.append(CameraDescriptor(
                    kind="chameleon",
                    label="Chameleon/FLIR serial %d (%s)" % (serial, itype),
                    id=serial,
                ))
            except Exception:
                continue
        return out

    # ──────────────────────────────────────────── selección / apertura

    def set_selected(self, desc: CameraDescriptor) -> None:
        """Selecciona y abre el backend correspondiente."""
        self.close()
        self.selected = desc
        from hal.factory import create_camera
        self._backend = create_camera(
            desc.kind,
            serial=desc.id,
            dll_dir=self.dll_dir,
            index=desc.id,
        )
        self._backend_kind = desc.kind
        self._backend.open()

    def read_frame_bgr(self):
        """Lee el frame actual del backend activo."""
        if self._backend is None:
            raise RuntimeError("Cámara no seleccionada.")
        return self._backend.read_frame_bgr()

    # ──────────────────────────────────────────── captura programática

    def request_capture(
        self,
        save_dir: str,
        base_name: str,
        kind: str = "pre",
        extra_meta: Optional[dict] = None,
    ) -> dict:
        """
        Captura 1 frame y guarda imagen + JSON de metadatos.
        Si hay ROI activo en _preview_state, también guarda la ROI.
        """
        if extra_meta is None:
            extra_meta = {}
        if self._backend is None or self.selected is None:
            raise RuntimeError("Cámara no abierta / no seleccionada.")

        os.makedirs(save_dir, exist_ok=True)
        ext = (self.photo_format or "png").lower().lstrip(".")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        seq = 1
        while True:
            fname = "%s_%s_%04d.%s" % (base_name, ts, seq, ext)
            path_full = os.path.join(save_dir, fname)
            if not os.path.exists(path_full):
                break
            seq += 1

        frame_bgr = self._backend.read_frame_bgr()
        safe_imwrite(path_full, frame_bgr, ext, jpg_quality=int(self.photo_quality))

        roi = None
        if isinstance(self._preview_state, dict):
            roi = self._preview_state.get("roi")

        out = {
            "timestamp_iso": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "image_path": path_full.replace("\\", "/"),
            "roi": roi,
            "camera": {
                "kind":  self.selected.kind,
                "id":    (int(self.selected.id)
                          if str(self.selected.id).isdigit()
                          else self.selected.id),
                "label": self.selected.label,
            },
        }

        path_roi = None
        if roi:
            try:
                x, y, rw, rh = [int(v) for v in roi]
                H2, W2 = frame_bgr.shape[:2]
                x  = max(0, min(x,  W2-1)); y  = max(0, min(y,  H2-1))
                rw = max(1, min(rw, W2-x)); rh = max(1, min(rh, H2-y))
                roi_img = frame_bgr[y:y+rh, x:x+rw].copy()
                path_roi = os.path.splitext(path_full)[0] + "_ROI." + ext
                safe_imwrite(path_roi, roi_img, ext, jpg_quality=int(self.photo_quality))
                out["roi_image_path"] = path_roi.replace("\\", "/")
            except Exception as e:
                out["roi_error"] = repr(e)

        if isinstance(extra_meta, dict):
            out.update(extra_meta)

        meta_path = os.path.splitext(path_full)[0] + ".json"
        out["meta_path"] = meta_path.replace("\\", "/")
        safe_write_json(meta_path, out)

        if path_roi:
            meta_roi = os.path.splitext(path_roi)[0] + ".json"
            out_roi = dict(out)
            out_roi["image_path"]       = out.get("roi_image_path")
            out_roi["full_image_path"]  = path_full.replace("\\", "/")
            out_roi["meta_path"]        = meta_roi.replace("\\", "/")
            safe_write_json(meta_roi, out_roi)

        return out

    # ──────────────────────────────────────────── helpers estáticos

    @staticmethod
    def generate_grid_points(roi_xywh, step_x: int, step_y: int,
                              serpentine: bool = True) -> list:
        """Genera lista de puntos de grilla para el scan plan."""
        x, y, w, h = roi_xywh
        step_x = max(1, int(step_x)); step_y = max(1, int(step_y))
        pts = []
        idx = 0
        rows = list(range(y, y + h, step_y))
        for r_i, yy in enumerate(rows):
            cols = list(range(x, x + w, step_x))
            if serpentine and (r_i % 2 == 1):
                cols = list(reversed(cols))
            for xx in cols:
                cx = int(min(x + w - 1, xx + step_x // 2))
                cy = int(min(y + h - 1, yy + step_y // 2))
                pts.append({"i": idx, "x": cx, "y": cy})
                idx += 1
        return pts

    @staticmethod
    def clamp_roi(x0, y0, x1, y1, W, H):
        x0 = max(0, min(int(x0), W-1)); x1 = max(0, min(int(x1), W-1))
        y0 = max(0, min(int(y0), H-1)); y1 = max(0, min(int(y1), H-1))
        if x1 < x0: x0, x1 = x1, x0
        if y1 < y0: y0, y1 = y1, y0
        return x0, y0, max(1, x1-x0+1), max(1, y1-y0+1)

    # ──────────────────────────────────────────── shim de compatibilidad

    def open_preview_tk(self, parent_tk, save_dir: str,
                        base_name: str = "microLIBS",
                        autoscale: bool = True,
                        max_update_fps: float = 8.0,
                        per_capture_metadata_cb=None,
                        stage=None,
                        jog_step_mm: float = 0.5,
                        on_close_cb=None) -> None:
        """
        Abre la ventana de preview.
        Delega a presentation.preview_panel.open_preview() manteniendo
        la interfaz original para compatibilidad con step0_wizard.py.
        """
        from presentation.preview_panel import open_preview
        open_preview(
            svc=self,
            parent_tk=parent_tk,
            save_dir=save_dir,
            base_name=base_name,
            autoscale=autoscale,
            max_update_fps=max_update_fps,
            stage=stage,
            jog_step_mm=jog_step_mm,
            on_close_cb=on_close_cb,
        )

    # ──────────────────────────────────────────── close

    def close(self) -> None:
        self._preview_state = None
        if self._backend is not None:
            try: self._backend.close()
            except Exception: pass
        self._backend = None
        self._backend_kind = None
        self.selected = None

    def safe_shutdown(self) -> None:
        """
        Apagado seguro de la cámara, delegando en la receta del driver.

        VisionService es el dueño de la cámara, así que es quien expone el
        método que el orquestador llama. Quién sabe QUÉ hay que hacer es el
        driver (`BaseCamera.safe_shutdown`): acá no se conoce ninguna marca.
        """
        if self._backend is not None:
            try:
                self._backend.safe_shutdown()
            except Exception:
                pass
        self.close()
