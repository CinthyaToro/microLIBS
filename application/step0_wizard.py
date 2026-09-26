# -*- coding: utf-8 -*-
"""
application/step0_wizard.py  (MINIMAL, estable)

Objetivo:
- No romper el flujo de mainL.
- Guardar artefactos básicos del Paso 0:
  - instrument_profile.json (stub, trazabilidad)
  - calibration.json (ROI + origen_px + mm_per_px + placeholders de stage)
  - (opcional) system_params.json (copia)

Incluye SOLO:
0.0 Resumen
0.3 Calibración imagen↔stage (mínimo)
0.5 Guardar y salir

Notas:
- Evita strings multilínea con comillas simples/dobles (causaron SyntaxError).
- No depende de ProfilesManager ni de planning.calibration.
- Usa el estado de preview si existe: vc._preview_state
"""

from __future__ import annotations

import logging
import os
import json
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


def safe_write_json(path: str, data: Dict[str, Any]) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class Step0Wizard:
    def __init__(self, parent, run_dir: str, system_params: Dict[str, Any], vc):
        self.parent = parent
        self.run_dir = os.path.abspath(run_dir)
        self.system_params = dict(system_params or {})
        self.vc = vc

        self.calibration_path = os.path.join(self.run_dir, "calibration.json")
        self.instrument_profile_path = os.path.join(self.run_dir, "instrument_profile.json")
        self.system_params_path = os.path.join(self.run_dir, "system_params.json")

        self._step = 0

        self.v_origin_mode = tk.StringVar(value="top_right")
        self.v_mmpx = tk.DoubleVar(value=0.0)
        self.v_stage_x0 = tk.DoubleVar(value=0.0)
        self.v_stage_y0 = tk.DoubleVar(value=0.0)
        self.v_stage_z0 = tk.DoubleVar(value=0.0)

        self._roi = None
        self._roi_origin_px = None

        self._build_ui()

    def _build_ui(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title("Paso 0 (mínimo) — microLIBS")
        self.win.geometry("860x560")
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        left = ttk.Frame(self.win, padding=10)
        left.pack(side="left", fill="y")

        right = ttk.Frame(self.win, padding=10)
        right.pack(side="right", fill="both", expand=True)

        self.lbl_status = ttk.Label(left, text=self._status_text(), justify="left")
        self.lbl_status.pack(anchor="nw", pady=(0, 10))

        self.lbl_step = ttk.Label(left, text="Paso 0.0 / 0.5", font=("Segoe UI", 10, "bold"))
        self.lbl_step.pack(anchor="nw", pady=(0, 10))

        self.btn_back = ttk.Button(left, text="Atrás", command=self.prev_step)
        self.btn_next = ttk.Button(left, text="Siguiente", command=self.next_step)
        self.btn_save = ttk.Button(left, text="Guardar y salir", command=self.save_and_exit)
        self.btn_cala = ttk.Button(left, text="Cal-A (tablero)", command=self._open_cala_panel)

        self.btn_back.pack(fill="x", pady=4)
        self.btn_next.pack(fill="x", pady=4)
        self.btn_save.pack(fill="x", pady=10)
        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=6)
        self.btn_cala.pack(fill="x", pady=4)

        self.content = ttk.Frame(right)
        self.content.pack(fill="both", expand=True)

        self._render_step()

    def _status_text(self) -> str:
        sp = self.system_params

        def g(k, default="—"):
            return sp.get(k, default)

        return (
            "Estado (según Wizard)\n"
            f"Stage: {g('stage_driver')}\n"
            f"Cámara: {g('camera_source')}\n"
            f"Trigger: {g('trigger_mode')}\n"
        )

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def _render_step(self):
        self._clear_content()
        self.lbl_step.configure(text=f"Paso 0.{self._step} / 0.5")
        self.lbl_status.configure(text=self._status_text())

        if self._step == 0:
            self._ui_00()
        elif self._step == 3:
            self._ui_03()
        else:
            self._ui_05()

        self.btn_back.state(["!disabled"] if self._step > 0 else ["disabled"])
        self.btn_next.state(["!disabled"] if self._step < 5 else ["disabled"])

    def next_step(self):
        if self._step == 0:
            self._step = 3
        elif self._step == 3:
            self._step = 5
        self._render_step()

    def prev_step(self):
        if self._step == 5:
            self._step = 3
        elif self._step == 3:
            self._step = 0
        self._render_step()

    def _on_close(self):
        if messagebox.askyesno("Salir", "¿Cerrar el Paso 0? (podés usar 'Guardar y salir')"):
            self.win.destroy()

    def run_modal(self):
        self.win.grab_set()
        self.parent.wait_window(self.win)

    def _build_calibration_payload(self) -> Dict[str, Any]:
        return {
            "created_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "roi_origin_mode": str(self.v_origin_mode.get()),
            "mm_per_px_x": float(self.v_mmpx.get()),
            "mm_per_px_y": float(self.v_mmpx.get()),
            "roi": (
                {"x": self._roi[0], "y": self._roi[1], "w": self._roi[2], "h": self._roi[3]}
                if self._roi
                else None
            ),
            "roi_origin_px": (
                {"x": self._roi_origin_px[0], "y": self._roi_origin_px[1]}
                if self._roi_origin_px
                else None
            ),
            "stage_origin_mm": {
                "x": float(self.v_stage_x0.get()),
                "y": float(self.v_stage_y0.get()),
                "z": float(self.v_stage_z0.get()),
            },
            "notes": "Paso 0 mínimo: escala isotrópica (2 puntos en preview o carga manual).",
        }

    def _build_instrument_profile_payload(self) -> Dict[str, Any]:
        return {
            "created_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "version": 1,
            "system_params_snapshot": self.system_params,
            "timing_calibration": {"status": "not_run"},
            "focus_z": {"status": "placeholder"},
            "notes": "",
        }

    def _save_all(self):
        os.makedirs(self.run_dir, exist_ok=True)
        safe_write_json(self.system_params_path, self.system_params)
        safe_write_json(self.instrument_profile_path, self._build_instrument_profile_payload())
        safe_write_json(self.calibration_path, self._build_calibration_payload())

    def save_and_exit(self):
        if float(self.v_mmpx.get() or 0.0) <= 0.0:
            if not messagebox.askyesno(
                "Calibración",
                "mm/px está en 0.\n\n¿Querés guardar igual?\n(Después el plan en mm no va a ser confiable.)",
            ):
                return

        self._save_all()
        messagebox.showinfo(
            "Guardado",
            "Listo.\n\nSe guardaron:\n- instrument_profile.json\n- calibration.json\n\nAhora mainL continúa con la sesión.",
        )
        self.win.destroy()

    def _ui_00(self):
        ttk.Label(self.content, text="0.0 — Resumen", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            self.content,
            text=(
                "Este Paso 0 mínimo guarda trazabilidad y calibración.\n"
                "En la siguiente pantalla configurás ROI/origen y escala mm/px.\n"
            ),
        ).pack(anchor="w", pady=(8, 10))

        box = tk.Text(self.content, height=16)
        box.pack(fill="both", expand=True)
        box.insert("1.0", json.dumps(self.system_params, ensure_ascii=False, indent=2))
        box.configure(state="disabled")

        ttk.Label(self.content, text="Siguiente: 0.3 Calibración imagen↔stage.").pack(anchor="w", pady=(10, 0))

    def _ui_03(self):
        ttk.Label(self.content, text="0.3 — Calibración imagen ↔ stage (mínimo)", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            self.content,
            text=(
                "Podés cargar ROI y origen_px desde el preview si ya está abierto.\n"
                "La escala mm/px se puede ingresar manualmente o traer desde la calibración 2 puntos del preview.\n"
            ),
        ).pack(anchor="w", pady=(8, 10))

        frm = ttk.Frame(self.content)
        frm.pack(fill="x", pady=6)

        ttk.Label(frm, text="Origen ROI:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            frm,
            textvariable=self.v_origin_mode,
            width=18,
            values=["top_right", "top_left", "bottom_right", "bottom_left", "center"],
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(frm, text="mm/px (isotrópico):").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(frm, textvariable=self.v_mmpx, width=14).grid(row=1, column=1, sticky="w", padx=6, pady=4)

        origin = ttk.LabelFrame(self.content, text="Origen del stage (mm) — placeholder/manual", padding=10)
        origin.pack(fill="x", pady=10)

        ttk.Label(origin, text="X0").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(origin, textvariable=self.v_stage_x0, width=12).grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(origin, text="Y0").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Entry(origin, textvariable=self.v_stage_y0, width=12).grid(row=0, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(origin, text="Z0").grid(row=0, column=4, sticky="w", padx=6, pady=4)
        ttk.Entry(origin, textvariable=self.v_stage_z0, width=12).grid(row=0, column=5, sticky="w", padx=6, pady=4)

        self.lbl_roi = ttk.Label(self.content, text="ROI: (no cargada)   Origen_px: (no cargado)")
        self.lbl_roi.pack(anchor="w", pady=(6, 8))

        btns = ttk.Frame(self.content)
        btns.pack(fill="x", pady=6)

        ttk.Button(btns, text="Abrir preview (definir ROI + origen)", command=self._open_preview_for_roi).pack(side="left", padx=6)
        ttk.Button(btns, text="Traer ROI / origen / mm/px del preview", command=self._pull_from_preview).pack(side="left", padx=6)

        ttk.Label(
            self.content,
            text=(
                "Tip: en el preview, ROI = click+arrastre; origen ROI = click derecho.\n"
                "Si tenés el botón 'Calibrar escala (2 puntos)' en el preview, también podés generar mm/px ahí.\n"
            ),
            foreground="gray",
        ).pack(anchor="w", pady=(12, 0))

    def _ui_05(self):
        ttk.Label(self.content, text="0.5 — Guardar y salir", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            self.content,
            text=(
                "Este Wizard mínimo solo guarda archivos.\n"
                "Luego mainL continúa con preview + panel de control + loop.\n"
            ),
        ).pack(anchor="w", pady=(8, 10))

        preview = {
            "instrument_profile_path": self.instrument_profile_path,
            "calibration_path": self.calibration_path,
            "calibration_preview": self._build_calibration_payload(),
        }

        box = tk.Text(self.content, height=18)
        box.pack(fill="both", expand=True)
        box.insert("1.0", json.dumps(preview, ensure_ascii=False, indent=2))
        box.configure(state="disabled")

        ttk.Label(self.content, text="Usá el botón 'Guardar y salir' a la izquierda.").pack(anchor="w", pady=(10, 0))

    def _open_preview_for_roi(self):
        try:
            images_dir = os.path.join(self.run_dir, "images_step0")
            os.makedirs(images_dir, exist_ok=True)
            self.vc.open_preview_tk(self.win, save_dir=images_dir, base_name="step0_cal")
            messagebox.showinfo(
                "Preview",
                "En el preview:\n"
                "- ROI: click+arrastre\n"
                "- Origen ROI: click derecho\n"
                "- (Opcional) escala: botón 'Calibrar escala (2 puntos)'\n\n"
                "Cerrá el preview y volvé al Wizard para 'Traer' los valores.",
            )
        except Exception as e:
            messagebox.showerror("Preview", repr(e))

    def _pull_from_preview(self):
        st = getattr(self.vc, "_preview_state", None)
        if not isinstance(st, dict):
            messagebox.showerror("Preview", "No hay preview abierto o no hay estado disponible.")
            return

        roi = st.get("roi")
        roi_origin_px = st.get("roi_origin_px")
        mm_per_px = st.get("mm_per_px")

        if roi is not None:
            try:
                self._roi = tuple(int(v) for v in roi)
            except Exception:
                self._roi = None

        if roi_origin_px is not None:
            try:
                self._roi_origin_px = (int(roi_origin_px[0]), int(roi_origin_px[1]))
            except Exception:
                self._roi_origin_px = None

        if mm_per_px is not None:
            try:
                self.v_mmpx.set(float(mm_per_px))
            except Exception:
                pass

        roi_str = str(self._roi) if self._roi else "(no)"
        org_str = str(self._roi_origin_px) if self._roi_origin_px else "(no)"
        self.lbl_roi.configure(text=f"ROI: {roi_str}   Origen_px: {org_str}")

        parts = []
        if mm_per_px is not None:
            parts.append(f"mm/px={float(mm_per_px):.6g}")
        if roi is not None:
            parts.append("ROI OK")
        if roi_origin_px is not None:
            parts.append("origen_px OK")
        messagebox.showinfo("Preview", "Leído del preview: " + (", ".join(parts) if parts else "(sin datos)"))

    # ------------------------------------------------------------------
    # Cal-A — calibracion homografica estatica (tablero de ajedrez)
    # Modo ADITIVO: no reemplaza el flujo 0.0→0.3→0.5 existente.
    # ------------------------------------------------------------------

    def _open_cala_panel(self):
        """Abre la ventana de Cal-A como Toplevel independiente."""
        win = tk.Toplevel(self.win)
        win.title("Cal-A — Calibracion homografica (tablero de ajedrez)")
        win.geometry("700x520")
        CalAPanel(win, run_dir=self.run_dir, operator=self.system_params.get("operator", ""))


class CalAPanel:
    """
    Panel de Cal-A: selecciona imagen, corre deteccion+homografia, muestra
    metricas y guarda el Perfil versionado. Capa presentation: llama a
    service/calibration_service.py y service/platform_profile.py.
    Todos los errores se muestran con messagebox.showerror (fail-loud).
    """

    INNER_CORNERS = (8, 6)
    SQUARE_MM     = 0.5
    SCALE_REF     = 218.0    # px/mm Chameleon CMLN-13S2M medida

    def __init__(self, parent, run_dir: str, operator: str = ""):
        self.parent   = parent
        self.run_dir  = run_dir
        self.operator = operator

        self._image_path: Optional[str]  = None
        self._profile:    Optional[dict]  = None
        self._debug_img:  Optional[object] = None   # ndarray BGR de la ultima deteccion

        self._build_ui()

    def _build_ui(self):
        frm = ttk.Frame(self.parent, padding=12)
        frm.pack(fill="both", expand=True)

        # --- seleccion de imagen ---
        ttk.Label(frm, text="Cal-A — Tablero de ajedrez", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(frm, text=(
            "Selecciona una imagen del tablero tomada con la Chameleon.\n"
            "El tablero debe llenar > 60% del FOV, sin reflejos ni zonas saturadas."
        )).pack(anchor="w", pady=(4, 10))

        img_frm = ttk.Frame(frm)
        img_frm.pack(fill="x")
        ttk.Button(img_frm, text="Seleccionar imagen...", command=self._select_image).pack(side="left")
        self.lbl_image = ttk.Label(img_frm, text="(ninguna)", foreground="gray")
        self.lbl_image.pack(side="left", padx=8)

        # --- parametros ---
        par_frm = ttk.LabelFrame(frm, text="Parametros", padding=8)
        par_frm.pack(fill="x", pady=8)

        ttk.Label(par_frm, text="Casilla (mm):").grid(row=0, column=0, sticky="w", padx=4)
        self.v_square_mm = tk.DoubleVar(value=self.SQUARE_MM)
        ttk.Entry(par_frm, textvariable=self.v_square_mm, width=8).grid(row=0, column=1, sticky="w", padx=4)

        ttk.Label(par_frm, text="Esquinas interiores (cols x rows):").grid(row=1, column=0, sticky="w", padx=4)
        self.v_cols = tk.IntVar(value=self.INNER_CORNERS[0])
        self.v_rows = tk.IntVar(value=self.INNER_CORNERS[1])
        ttk.Entry(par_frm, textvariable=self.v_cols, width=5).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(par_frm, text="x").grid(row=1, column=2)
        ttk.Entry(par_frm, textvariable=self.v_rows, width=5).grid(row=1, column=3, sticky="w", padx=4)

        ttk.Label(par_frm, text="Escala ref. (px/mm):").grid(row=2, column=0, sticky="w", padx=4)
        self.v_scale_ref = tk.DoubleVar(value=self.SCALE_REF)
        ttk.Entry(par_frm, textvariable=self.v_scale_ref, width=8).grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(par_frm, text="Operador:").grid(row=3, column=0, sticky="w", padx=4)
        self.v_operator = tk.StringVar(value=self.operator)
        ttk.Entry(par_frm, textvariable=self.v_operator, width=20).grid(row=3, column=1, columnspan=3, sticky="w", padx=4)

        # --- boton correr ---
        ttk.Button(frm, text="Correr Cal-A", command=self._run_cala).pack(pady=8)

        # --- resultados ---
        res_frm = ttk.LabelFrame(frm, text="Resultados", padding=8)
        res_frm.pack(fill="both", expand=True)
        self.txt_result = tk.Text(res_frm, height=12, state="disabled", wrap="word")
        self.txt_result.pack(fill="both", expand=True)

        btn_row2 = ttk.Frame(frm)
        btn_row2.pack(fill="x", pady=(4, 0))
        ttk.Button(btn_row2, text="Guardar Perfil Cal-A",
                   command=self._save_profile).pack(side="left", padx=(0, 6))
        ttk.Button(btn_row2, text="Ver imagen debug",
                   command=self._show_debug_image).pack(side="left")

    def _select_image(self):
        path = filedialog.askopenfilename(
            title="Seleccionar imagen del tablero",
            filetypes=[("Imagenes", "*.png *.jpg *.tiff *.tif *.bmp"), ("Todos", "*.*")],
        )
        if path:
            self._image_path = path
            self.lbl_image.configure(text=os.path.basename(path), foreground="black")
            self._profile = None

    def _run_cala(self):
        if not self._image_path:
            messagebox.showerror("Cal-A", "Selecciona una imagen primero.")
            return

        try:
            import cv2
            import numpy as np
            from service.calibration_service import (
                to_gray,
                sharpness_score, check_exposure, load_dead_pixel_mask,
                detect_chessboard_ex, suggest_board_sizes, image_diagnostics,
                compute_homography, validate_calibration,
            )
            from service.platform_profile import build_profile
            from tests.fixtures.synthetic_board import board_corners_mm_nominal

        except ImportError as e:
            messagebox.showerror("Cal-A", f"Modulo no disponible: {e}")
            return

        try:
            # Cargar con IMREAD_UNCHANGED para preservar el formato original
            # (evita que IMREAD_GRAYSCALE falle silenciosamente con formatos
            # poco comunes como TIFFs de 2 canales de la Celestron).
            # to_gray() normaliza a 1 canal uint8 cualquiera sea el origen.
            img_raw = cv2.imread(self._image_path, cv2.IMREAD_UNCHANGED)
            if img_raw is None:
                raise RuntimeError(f"No se pudo leer la imagen: {self._image_path}")
            img_raw = to_gray(img_raw)

            # Mascara neutra — se define siempre antes de cualquier chequeo.
            # Para camaras sin defectos conocidos (ej. Celestron) queda todo-False.
            # Para la Chameleon CMLN-13S2M actualizar columns y cluster_bbox.
            mask = load_dead_pixel_mask(
                img_raw.shape,
                columns=[],        # ej. [482, 1021] para la Chameleon real
                cluster_bbox=None, # ej. (410, 620, 430, 650) para el rombo
            )

            # Diagnostico de imagen (usado en mensajes de error)
            diag = image_diagnostics(img_raw, mask)

            # Poka-yoke 3: nitidez
            sharp = diag["sharpness"]
            if sharp < 50.0:
                raise RuntimeError(
                    f"Imagen demasiado desenfocada (sharpness={sharp:.1f} < 50).\n"
                    f"  Resolucion: {diag['resolucion'][0]}x{diag['resolucion'][1]} px\n"
                    f"  Contraste:  min={diag['pmin']} max={diag['pmax']} "
                    f"media={diag['pmean']:.1f} σ={diag['pstd']:.1f}\n"
                    "Enfoca el tablero antes de calibrar."
                )

            # Poka-yoke 4: exposicion (excluye pixeles muertos del calculo)
            exp = check_exposure(img_raw, mask)
            if not exp["ok"]:
                raise RuntimeError(
                    f"Exposicion inadecuada:\n"
                    f"  saturados={exp['saturated_frac']:.1%}  "
                    f"oscuros={exp['underexposed_frac']:.1%}\n"
                    f"  Histograma: dark={diag['pct_dark']:.0%} "
                    f"mid={diag['pct_mid']:.0%} bright={diag['pct_bright']:.0%}\n"
                    "Ajusta la exposicion de la camara."
                )

            inner = (int(self.v_cols.get()), int(self.v_rows.get()))
            sq_mm = float(self.v_square_mm.get())

            # Deteccion — version extendida para obtener imagen de debug
            corners, debug_img, det_msg = detect_chessboard_ex(
                img_raw, mask, inner_corners=inner
            )
            self._debug_img = debug_img   # disponible para "Ver debug"
            # Guardar imagen de debug automaticamente, tanto en exito como en fallo.
            # En fallo: gris sin esquinas (lo que vio el detector).
            # En exito: esquinas dibujadas con drawChessboardCorners.
            debug_path = self._save_debug_img(debug_img)

            if corners is None:
                # Intentar sugerir tamaños alternativos
                alts = suggest_board_sizes(img_raw, mask,
                       candidates=[(7,5),(9,6),(6,4),(5,4),(9,7),(7,7),(6,6),(10,7)])
                alt_txt = ""
                if alts:
                    alt_txt = "\n\nPatrones detectados en la misma imagen:\n" + "\n".join(
                        f"  {a['inner'][0]}x{a['inner'][1]}  ({a['n_corners']} esq.)"
                        for a in alts
                    )
                else:
                    alt_txt = "\n\nNingún patrón alternativo detectado."

                debug_hint = (f"\n\nImagen de debug guardada en:\n  {debug_path}"
                              if debug_path else "\n\nUsa 'Ver imagen debug' para ver qué detectó OpenCV.")
                raise RuntimeError(
                    f"No se detectaron esquinas con patron {inner[0]}x{inner[1]}.\n\n"
                    f"  Imagen: {diag['resolucion'][0]}x{diag['resolucion'][1]} px  "
                    f"({diag['n_canales']} canal)\n"
                    f"  Sharpness: {sharp:.1f}\n"
                    f"  Contraste: min={diag['pmin']} max={diag['pmax']} "
                    f"media={diag['pmean']:.1f} σ={diag['pstd']:.1f}\n"
                    f"  Histograma: dark={diag['pct_dark']:.0%} "
                    f"mid={diag['pct_mid']:.0%} bright={diag['pct_bright']:.0%}"
                    + alt_txt + debug_hint
                )

            # Homografia
            mm_nom = board_corners_mm_nominal(inner_corners=inner, square_mm=sq_mm)
            H, metrics = compute_homography(corners, mm_nom)

            # Validacion
            result = validate_calibration(
                metrics, H,
                rms_um_max=30.0,
                min_corners=int(inner[0] * inner[1] * 0.85),
                scale_px_per_mm_ref=float(self.v_scale_ref.get()),
            )

            # Construir perfil
            camara = {"modelo": "CMLN-13S2M", "serial": "",
                      "resolucion": list(img_raw.shape[::-1]), "px_um": 3.75,
                      "mascara_defectos": {}}
            optica = {"f_mm": 55, "iris_mm": 10.5, "f_num": 5.2, "difraccion_um": 3.5}
            px_mm  = float(self.v_scale_ref.get())
            escala = {"px_por_mm": px_mm, "um_por_px": 1000.0 / px_mm if px_mm else 0,
                      "aumento": 0.82, "fov_mm": [round(img_raw.shape[1] / px_mm, 2),
                                                   round(img_raw.shape[0] / px_mm, 2)]}
            patron = {"tipo": "ajedrez", "casilla_mm": sq_mm,
                      "casillas": [inner[0] + 1, inner[1] + 1],
                      "esquinas": int(inner[0] * inner[1])}
            metricas = {**metrics}
            checks_prof = {
                "nitidez_ok":     True,
                "saturacion_ok":  exp["ok"],
                "espejado_ok":    result["checks"]["espejado_ok"],
                "escala_cross_ok": result["checks"]["escala_cross_ok"],
            }

            self._profile = build_profile(
                camara=camara, optica=optica, escala=escala, patron=patron,
                H=H,
                puntos_crudos={"px": corners.tolist(), "mm_nominal": mm_nom.tolist()},
                metricas=metricas, checks=checks_prof,
                operador=str(self.v_operator.get()),
            )

            # Mostrar resultados
            status = "PASO" if result["passed"] else "FALLO"
            lines = [
                f"=== Cal-A {status} ===",
                f"Deteccion  : {det_msg}",
                f"Esquinas   : {metrics['esquinas_detectadas']}",
                f"RMS        : {metrics['rms_um']:.2f} um  ({metrics['rms_px']:.3f} px)",
                f"det_lineal : {metrics['det_lineal']:.4f}",
                f"isotropia  : {metrics['isotropia_xy']:.4f}",
                f"sharpness  : {sharp:.1f}",
                f"Imagen     : {diag['resolucion'][0]}x{diag['resolucion'][1]} px  "
                f"min={diag['pmin']} max={diag['pmax']} σ={diag['pstd']:.1f}",
                "",
                "Checks:",
            ]
            for k, v in result["checks"].items():
                lines.append(f"  {k:20s} {'OK' if v else 'FALLO'}")
            if debug_path:
                lines.append("")
                lines.append(f"Debug: {debug_path}")
            if not result["passed"]:
                lines.append("")
                lines.append("ADVERTENCIA: la calibracion no paso todos los checks.")
                lines.append("No guardes este perfil sin revisar los fallos.")

            self._show_result("\n".join(lines))
            log.info("Cal-A: %s | rms_um=%.2f | esquinas=%d",
                     status, metrics["rms_um"], metrics["esquinas_detectadas"])

        except Exception as e:
            log.exception("Cal-A fallo: %s", e)
            messagebox.showerror("Cal-A", str(e))

    def _save_profile(self):
        if self._profile is None:
            messagebox.showerror("Guardar", "Corre Cal-A primero.")
            return

        # TODO(Cal-A pipeline): este perfil NO está conectado al pipeline de scan.
        # El pipeline usa StageCalibration (afín, movimiento del stage), no esta homografía.
        # Para conectarlo: (1) decidir si la imagen de entrada es siempre el sensor completo
        # (1280×960) o si se admite recorte; si se admite recorte, guardar el offset
        # (x0_crop, y0_crop) en el perfil para corregir el origen al convertir px→mm.
        # (2) Cargar H en VisionService/ScanRunner y reemplazar StageCalibration.px_to_mm().

        default_name = os.path.join(self.run_dir, "perfil_calibracion.json")
        path = filedialog.asksaveasfilename(
            title="Guardar Perfil Cal-A",
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return

        try:
            from service.platform_profile import save_profile
            saved = save_profile(self._profile, path)
            messagebox.showinfo("Guardado", f"Perfil guardado en:\n{saved}")
            log.info("Perfil Cal-A guardado: %s", saved)
        except Exception as e:
            log.exception("Error guardando perfil Cal-A: %s", e)
            messagebox.showerror("Guardar", str(e))

    def _save_debug_img(self, debug_img) -> "Optional[str]":
        """
        Guarda debug_img en run_dir/debug_cala.png.
        Retorna la ruta guardada, o None si falla (no lanza excepcion).
        """
        try:
            import cv2
            os.makedirs(self.run_dir, exist_ok=True)
            path = os.path.join(self.run_dir, "debug_cala.png")
            cv2.imwrite(path, debug_img)
            log.info("Cal-A debug guardado: %s", path)
            return path
        except Exception as exc:
            log.warning("No se pudo guardar debug_cala.png: %s", exc)
            return None

    def _show_debug_image(self):
        """
        Abre un Toplevel con la imagen de debug de la ultima deteccion:
          - esquinas dibujadas si la deteccion fue exitosa
          - imagen en gris con texto 'NO DETECTADO' si fallo
        Si no hay imagen todavia, avisa al operador.
        """
        if self._debug_img is None:
            messagebox.showinfo("Debug", "Correr Cal-A primero para generar la imagen de debug.")
            return

        try:
            import cv2
            from PIL import Image, ImageTk

            dbg = self._debug_img
            # Escalar para que quepa en pantalla (max 900 px de ancho)
            H, W = dbg.shape[:2]
            scale = min(1.0, 900 / max(W, 1))
            if scale < 1.0:
                dbg = cv2.resize(dbg, (int(W * scale), int(H * scale)),
                                 interpolation=cv2.INTER_AREA)
                H, W = dbg.shape[:2]

            rgb = cv2.cvtColor(dbg, cv2.COLOR_BGR2RGB)
            imgtk = ImageTk.PhotoImage(Image.fromarray(rgb))

            win = tk.Toplevel(self.parent)
            win.title("Cal-A — imagen de debug")
            win.resizable(True, True)

            canvas = tk.Canvas(win, width=W, height=H, bg="#111")
            canvas.pack(fill="both", expand=True)
            canvas.create_image(0, 0, anchor="nw", image=imgtk)
            canvas.image = imgtk   # evitar GC

            debug_path = os.path.join(self.run_dir, "debug_cala.png")
            tk.Label(win, text=f"Archivo: {debug_path}",
                     font=("", 8), fg="#555").pack(anchor="w", padx=4)

        except Exception as e:
            log.exception("Error mostrando debug Cal-A: %s", e)
            messagebox.showerror("Debug", str(e))

    def _show_result(self, text: str):
        self.txt_result.configure(state="normal")
        self.txt_result.delete("1.0", "end")
        self.txt_result.insert("1.0", text)
        self.txt_result.configure(state="disabled")
