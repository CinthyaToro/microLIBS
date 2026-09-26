# -*- coding: utf-8 -*-
"""
application/session_manager.py
================================
Gestión del ciclo de vida de una sesión de medición.

Estructura de sesión:
  <base_dir>/<muestra>/session_<timestamp>/
      images/
      events/
      session.json
      system_params.json
      calibration.json
      scan_plan.json
      instrument_profile.json
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Optional


def sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "muestra_sin_nombre"
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name


def safe_write_json(path: str, data: dict) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class SessionManager:

    # Archivo de settings persistentes (en la raíz del proyecto)
    @property
    def SETTINGS_FILE(self) -> str:
        from paths import PROJECT_ROOT
        return str(PROJECT_ROOT / "last_settings.json")

    def __init__(self):
        self.session_dir: Optional[str] = None
        self.images_dir:  Optional[str] = None
        self.events_dir:  Optional[str] = None
        self.sample_name: str = ""
        self.operator:    str = ""
        self._ts:         str = ""

    # ──────────────────────────────────────────── creación

    def create(self, base_dir: str, sample_name: str, operator: str = "") -> dict:
        """Crea la estructura de directorios. Retorna dict con las rutas."""
        self.sample_name = sanitize_name(sample_name)
        self.operator    = operator
        self._ts         = time.strftime("%Y%m%d_%H%M%S")
        sample_dir       = os.path.join(base_dir, self.sample_name)
        self.session_dir = os.path.join(sample_dir, "session_%s" % self._ts)
        self.images_dir  = os.path.join(self.session_dir, "images")
        self.events_dir  = os.path.join(self.session_dir, "events")
        os.makedirs(self.images_dir, exist_ok=True)
        os.makedirs(self.events_dir, exist_ok=True)
        return {"session_dir": self.session_dir,
                "images_dir":  self.images_dir,
                "events_dir":  self.events_dir,
                "ts":          self._ts}

    # ──────────────────────────────────────────── validación

    @staticmethod
    def validate_base_dir(base_dir: str) -> None:
        """Verifica que base_dir sea escribible. Lanza ValueError si no."""
        os.makedirs(base_dir, exist_ok=True)
        test = os.path.join(base_dir, ".__microlibs_write_test__.tmp")
        try:
            with open(test, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(test)
        except Exception as e:
            raise ValueError(
                "No se puede escribir en la carpeta base:\n%s\n\nDetalle: %s" % (base_dir, e)
            )

    # ──────────────────────────────────────────── metadatos

    def write_session_json(self, vc_selected, stage_driver: str,
                            trigger_mode: str, arduino_cfg: dict,
                            extra: dict = None) -> str:
        try:
            import cv2; opencv_ver = cv2.__version__
        except Exception:
            opencv_ver = None

        data = {
            "created_iso":  time.strftime("%Y-%m-%dT%H:%M:%S"),
            "sample_name":  self.sample_name,
            "operator":     self.operator,
            "session_dir":  self.session_dir,
            "images_dir":   self.images_dir,
            "events_dir":   self.events_dir,
            "camera": {
                "kind":  vc_selected.kind  if vc_selected else None,
                "id":    (int(vc_selected.id)
                          if vc_selected and str(getattr(vc_selected, "id","")).isdigit()
                          else (vc_selected.id if vc_selected else None)),
                "label": vc_selected.label if vc_selected else None,
            },
            "stage":   {"driver": stage_driver},
            "trigger": {"mode": trigger_mode},
            "arduino": arduino_cfg,
            "environment": {
                "python":   sys.version,
                "platform": platform.platform(),
                "opencv":   opencv_ver,
            },
        }
        if extra:
            data.update(extra)
        path = os.path.join(self.session_dir, "session.json")
        safe_write_json(path, data)
        return path

    def write_system_params(self, params: dict) -> str:
        path = os.path.join(self.session_dir, "system_params.json")
        safe_write_json(path, params)
        return path

    # ──────────────────────────────────────────── settings persistentes

    def load_settings(self) -> dict:
        try:
            p = self.SETTINGS_FILE
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    s = json.load(f)
                if "base_dir" in s:
                    s["base_dir"] = os.path.expanduser(s["base_dir"])
                return s
        except Exception:
            pass
        return {}

    def save_settings(self, s: dict) -> None:
        try:
            p = self.SETTINGS_FILE
            to_save = dict(s)
            if "base_dir" in to_save:
                home = str(Path.home())
                bd = str(to_save["base_dir"])
                if bd.startswith(home):
                    to_save["base_dir"] = "~" + bd[len(home):].replace("\\", "/")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(to_save, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
