# -*- coding: utf-8 -*-
"""
presentation/preview_panel.py  (v4.0 — profile-aware)
=======================================================

Panel de preview + planificación del scan.

CAMBIOS v4:
- Profile-aware: el panel de jog muestra solo los ejes que el hardware tiene.
  Home solo aparece donde el perfil lo indica (Thorlabs sí, MoVi no).
  Pasos de jog por defecto según el hardware.
- Tres modos de definición de puntos del scan:
    · Clicks:  click sobre la imagen → punto numerado.
    · Grilla:  parámetros de barrido (paso X/Y, serpentina, origen).
    · CSV:     cargar archivo con columnas x_mm,y_mm ó px,py.
- El ROI (click+drag) valida que la zona elegida sea alcanzable por el stage.
- scan_plan.json incluye coordenadas mm cuando hay calibración activa.
- Interfaz backward-compatible: open_preview() acepta los mismos parámetros
  de v3 más `profile=None` opcional al final.
"""

from __future__ import annotations

import csv
import json
import os
import threading
import time
from typing import Callable, List, Optional, Tuple

import cv2
from service.vision_service import VisionService, safe_write_json
from service.calibration_service import StageCalibration


# ---------------------------------------------------------------------------
# Entrada pública
# ---------------------------------------------------------------------------

def open_preview(
    svc: VisionService,
    parent_tk,
    save_dir: str,
    base_name: str = "microLIBS",
    autoscale: bool = True,
    max_update_fps: float = 8.0,
    stage=None,
    jog_step_mm: float = 0.5,
    on_close_cb: Optional[Callable] = None,
    profile=None,           # PlatformProfile (opcional; se deriva si None)
    dead_pixel_mask=None,   # ndarray bool (H,W) de píxeles muertos — opcional
    calibration=None,       # StageCalibration precargada; si None se auto-carga
) -> None:
    """
    Abre la ventana de preview + planificación del scan.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk, filedialog
    from PIL import Image, ImageTk

    if svc._backend is None:
        raise RuntimeError("No hay cámara seleccionada. Llamá a svc.set_selected() primero.")

    # ── Resolver perfil ──────────────────────────────────────────────────────
    if profile is None:
        try:
            from application.platform_profile import PlatformProfile
            profile = PlatformProfile.from_hardware(stage)
        except Exception:
            profile = _FallbackProfile(stage)

    os.makedirs(save_dir, exist_ok=True)
    session_dir    = os.path.abspath(os.path.join(save_dir, os.pardir))
    scan_plan_path = os.path.join(session_dir, "scan_plan.json")
    calib_dir      = os.path.join(os.path.dirname(session_dir), "calibrations")

    # ── Estado global ────────────────────────────────────────────────────────
    state = {
        "n": 0, "paused": False,
        "last_bgr": None, "last_pix": None, "frame_ready": False,
        "roi": None,                    # (x1,y1,x2,y2) en px imagen original
        "dragging": False, "drag_start_disp": None, "drag_curr_disp": None,
        "disp_scale": 1.0, "disp_w": None, "disp_h": None,
        "disp_offx": 0, "disp_offy": 0,
        "alive": True,
        "calibration": None,
        # Puntos del plan (modo clicks)
        "click_points": [],             # lista de (px, py)
        # Modo activo del planificador
        "plan_mode": "clicks",          # "clicks" | "grid" | "csv"
        # Puntos finales del plan (resultado de cualquier modo)
        "plan_points": [],              # lista de {"px","py","x_mm","y_mm"}
        # Focus Assist
        "focus_assist": {
            "enabled":         False,
            "score":           None,    # float — varianza del Laplaciano
            "max_score":       None,    # float — máximo histórico desde el reset
            "error":           None,    # str   — mensaje de error o None
            "roi_frac":        0.40,    # tamaño del ROI como fracción de la imagen
            # Centro del ROI en fracción de (W, H).
            # Default: cuadrante sup. izq. (0.28, 0.25) para evitar el rombo
            # central de la Chameleon CMLN-13S2M que cae en (0.5, 0.5).
            "roi_cx_frac":     0.28,
            "roi_cy_frac":     0.25,
        },
    }
    svc._preview_state = state

    # ── Ventana ──────────────────────────────────────────────────────────────
    win = tk.Toplevel(parent_tk)
    win.title("Preview microLIBS — %s  [%s]" % (
        svc.selected.label if svc.selected else "",
        profile.stage_driver.upper() if profile.stage_driver else "sin stage"))
    win.geometry("1320x920")
    win.minsize(900, 600)

    # ── Barra de calibración ─────────────────────────────────────────────────
    calib_bar = tk.Frame(win)
    calib_bar.pack(fill="x", padx=8, pady=(6, 2))

    calib_status_var = tk.StringVar(value="⚠  Sin calibración — los puntos no tendrán coordenadas mm")
    calib_status_lbl = tk.Label(calib_bar, textvariable=calib_status_var,
                                anchor="w", fg="#b71c1c", font=("", 9))
    calib_status_lbl.pack(side="left", fill="x", expand=True)

    def _apply_calibration(cal):
        state["calibration"] = cal
        if cal and cal.valid:
            sx = cal.scale_x_mm_per_px()
            sy = cal.scale_y_mm_per_px()
            rot = cal.rotation_deg()
            suspicious, reason = cal.looks_suspicious()
            if suspicious:
                calib_status_var.set(
                    "⚠ CALIBRACIÓN SOSPECHOSA | rot %.1f° | sx=%.4f sy=%.4f mm/px | %s"
                    % (rot, sx, sy, reason[:120]))
                calib_status_lbl.configure(fg="#b71c1c")
            else:
                calib_status_var.set(
                    "✅  Calibrado | %.4f mm/px X | %.4f mm/px Y | rot %.2f° | res %.4f mm"
                    % (sx, sy, rot, cal.residual_mm))
                calib_status_lbl.configure(fg="#1b5e20")
            _rebuild_plan()
        else:
            calib_status_var.set("⚠  Sin calibración — los puntos no tendrán coordenadas mm")
            calib_status_lbl.configure(fg="#b71c1c")

    def _open_calib_wizard():
        from presentation.calibration_wizard import open_calibration_wizard
        open_calibration_wizard(
            parent=win, vc=svc, stage=stage,
            session_dir=session_dir, calib_dir=calib_dir,
            stage_driver=profile.stage_driver,
            on_done=_apply_calibration,
            profile=profile)

    def _load_calib_file():
        path = filedialog.askopenfilename(
            title="Cargar calibración",
            initialdir=calib_dir if os.path.isdir(calib_dir) else session_dir,
            filetypes=[("Calibración JSON", "*.json"), ("Todos", "*.*")])
        if path:
            try: _apply_calibration(StageCalibration.load(path))
            except Exception as e:
                messagebox.showerror("Calibración", "Error al cargar: %s" % e)

    tk.Button(calib_bar, text="🔧 Calibrar...", width=14,
              command=_open_calib_wizard).pack(side="right", padx=(4, 0))
    tk.Button(calib_bar, text="📂 Cargar cal.", width=14,
              command=_load_calib_file).pack(side="right", padx=4)

    # ── Helpers de plan — definidos antes de _apply_calibration que los llama ──
    def _update_plan_listbox():
        lb = state.get("_listbox")
        cv = state.get("_count_var")
        if lb is None:
            return
        lb.delete(0, "end")
        pts = state["plan_points"]
        for i, p in enumerate(pts):
            if "x_mm" in p and "y_mm" in p:
                line = "%3d: (%.3f, %.3f) mm" % (i+1, p["x_mm"], p["y_mm"])
            else:
                line = "%3d: px=(%d, %d)" % (i+1, p.get("px", 0), p.get("py", 0))
            lb.insert("end", line)
        if cv:
            cv.set("%d puntos" % len(pts))

    def _rebuild_plan():
        """Reconstruye state['plan_points'] según el modo activo."""
        cal   = state["calibration"]
        mode  = state["plan_mode"]
        pts   = []

        if mode == "clicks":
            for px, py in state["click_points"]:
                pt = {"px": px, "py": py}
                if cal and cal.valid:
                    try:
                        xm, ym = cal.px_to_mm(px, py)
                        pt["x_mm"] = round(xm, 6)
                        pt["y_mm"] = round(ym, 6)
                    except Exception:
                        pass
                pts.append(pt)

        state["plan_points"] = pts
        _update_plan_listbox()

    state["_rebuild_plan"]         = _rebuild_plan
    state["_update_plan_listbox"]  = _update_plan_listbox

    # Aplicar calibración: la precargada por main.py tiene prioridad; si no
    # viene, intentar auto-cargar desde el directorio persistente.
    if calibration is not None and calibration.valid:
        _apply_calibration(calibration)
    else:
        try:
            _cam_lbl = svc.selected.label if svc.selected else ""
            _cal_auto = StageCalibration.load_persistent(
                calib_dir, profile.stage_driver, _cam_lbl)
            if _cal_auto and _cal_auto.valid:
                _apply_calibration(_cal_auto)
        except Exception:
            pass

    # ── Frame principal ──────────────────────────────────────────────────────
    main_frame = tk.Frame(win)
    main_frame.pack(fill="both", expand=True, padx=6, pady=4)

    # Canvas de imagen
    img_canvas = tk.Canvas(main_frame, bg="#111", cursor="crosshair")
    img_canvas.pack(side="left", fill="both", expand=True)

    # Panel derecho con scroll — envuelve el contenido en Canvas+Scrollbar
    right_outer = tk.Frame(main_frame, width=290, bd=1, relief="groove")
    right_outer.pack(side="right", fill="y", padx=(6, 0))
    right_outer.pack_propagate(False)

    _rp_sb = tk.Scrollbar(right_outer, orient="vertical")
    _rp_sb.pack(side="right", fill="y")
    _rp_canvas = tk.Canvas(right_outer, yscrollcommand=_rp_sb.set,
                           bd=0, highlightthickness=0)
    _rp_canvas.pack(side="left", fill="both", expand=True)
    _rp_sb.config(command=_rp_canvas.yview)

    right_panel = tk.Frame(_rp_canvas)
    _rp_win_id = _rp_canvas.create_window((0, 0), window=right_panel, anchor="nw")

    def _rp_on_configure(event):
        _rp_canvas.configure(scrollregion=_rp_canvas.bbox("all"))
    right_panel.bind("<Configure>", _rp_on_configure)

    def _rp_on_canvas_resize(event):
        _rp_canvas.itemconfig(_rp_win_id, width=event.width)
    _rp_canvas.bind("<Configure>", _rp_on_canvas_resize)

    def _rp_mousewheel(event):
        _rp_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _rp_bind_scroll(widget):
        widget.bind("<Enter>", lambda e: _rp_canvas.bind_all("<MouseWheel>", _rp_mousewheel))
        widget.bind("<Leave>", lambda e: _rp_canvas.unbind_all("<MouseWheel>"))

    _rp_bind_scroll(right_outer)
    _rp_bind_scroll(_rp_canvas)
    _rp_bind_scroll(right_panel)

    # ── Panel de jog (profile-aware) ─────────────────────────────────────────
    if profile.has_stage():
        _build_jog_panel(right_panel, stage, profile, win)

    ttk.Separator(right_panel, orient="horizontal").pack(fill="x", padx=4, pady=4)

    # ── Panel de Focus Assist ─────────────────────────────────────────────────
    # IMPORTANTE: debe ir ANTES de _build_plan_panel porque el plan usa
    # expand=True y consumiría todo el espacio restante, dejando el panel
    # de foco fuera de la región visible.
    _build_focus_assist_panel(right_panel, state, win)
    ttk.Separator(right_panel, orient="horizontal").pack(fill="x", padx=4, pady=2)

    # ── Panel de planificación del scan ──────────────────────────────────────
    _build_plan_panel(
        right_panel, state, profile, win, img_canvas,
        scan_plan_path, session_dir, save_dir, base_name,
        lambda: svc.selected.label if svc.selected else "")

    # ── Captura de frames ────────────────────────────────────────────────────
    _imref = [None]
    state["cam_error"] = None

    def _capture_loop():
        # Warm-up: algunas webcams DirectShow devuelven frames negros o
        # lanzan error en las primeras lecturas. Hacemos hasta 10 intentos
        # antes de rendirse y mostrar el error.
        warmup_ok = False
        for attempt in range(10):
            if not state["alive"]:
                return
            try:
                frame = svc.read_frame_bgr()
                if frame is not None and frame.size > 0:
                    state["last_bgr"]    = frame
                    state["frame_ready"] = True
                    state["cam_error"]   = None
                    warmup_ok = True
                    break
            except Exception as e:
                state["cam_error"] = repr(e)
            time.sleep(0.2)

        if not warmup_ok:
            err = state.get("cam_error") or "sin respuesta"
            state["cam_error"] = "⚠ Cámara no responde: " + err
            # Intentar reabrir el backend
            try:
                svc._backend.close()
                time.sleep(0.5)
                svc._backend.open()
            except Exception:
                pass

        # Loop principal de captura
        consecutive_errors = 0
        while state["alive"]:
            if not state["paused"]:
                try:
                    frame = svc.read_frame_bgr()
                    if frame is not None and frame.size > 0:
                        state["last_bgr"]    = frame
                        state["frame_ready"] = True
                        state["cam_error"]   = None
                        consecutive_errors   = 0
                except Exception as e:
                    consecutive_errors += 1
                    state["cam_error"] = "⚠ Error cámara: " + repr(e)
                    if consecutive_errors >= 5:
                        # Intentar reabrir
                        try:
                            svc._backend.close()
                            time.sleep(0.5)
                            svc._backend.open()
                            consecutive_errors = 0
                        except Exception:
                            pass
            time.sleep(1.0 / max(1.0, max_update_fps))

    threading.Thread(target=_capture_loop, daemon=True).start()
    threading.Thread(
        target=_focus_assist_loop,
        args=(state, dead_pixel_mask),
        daemon=True,
    ).start()

    def _update_display():
        if not state["alive"] or not win.winfo_exists():
            return
        if state["frame_ready"] and state["last_bgr"] is not None:
            state["frame_ready"] = False
            _redraw_canvas(img_canvas, state, _imref, profile)
        elif state.get("cam_error") and state["last_bgr"] is None:
            try:
                cw = img_canvas.winfo_width()
                ch = img_canvas.winfo_height()
                img_canvas.delete("all")
                img_canvas.create_text(
                    max(cw // 2, 200), max(ch // 2, 100),
                    text=state["cam_error"],
                    fill="#ff5555", font=("Courier", 10), anchor="center")
            except Exception:
                pass
        win.after(int(1000 / max_update_fps), _update_display)

    # ── Interacción con el canvas ────────────────────────────────────────────
    def _on_canvas_click(ev):
        if state["last_bgr"] is None:
            return
        px, py = _disp_to_img(ev.x, ev.y, state)
        if px is None:
            return

        mode = state["plan_mode"]
        if mode == "clicks":
            state["click_points"].append((px, py))
            _rebuild_plan()
        elif mode == "roi_drag":
            pass  # handled by press/release

    def _on_press(ev):
        state["dragging"] = True
        state["drag_start_disp"] = (ev.x, ev.y)
        state["drag_curr_disp"]  = (ev.x, ev.y)

    def _on_drag(ev):
        if state["dragging"]:
            state["drag_curr_disp"] = (ev.x, ev.y)

    def _on_release(ev):
        if not state["dragging"]:
            return
        state["dragging"] = False
        x1d, y1d = state["drag_start_disp"]
        x2d, y2d = ev.x, ev.y
        if abs(x2d - x1d) < 5 and abs(y2d - y1d) < 5:
            # Pequeño drag = click
            _on_canvas_click(ev)
            state["drag_start_disp"] = None
            return
        # ROI drag
        px1, py1 = _disp_to_img(x1d, y1d, state)
        px2, py2 = _disp_to_img(x2d, y2d, state)
        if None not in (px1, py1, px2, py2):
            x1, x2 = sorted([px1, px2])
            y1, y2 = sorted([py1, py2])
            state["roi"] = (x1, y1, x2, y2)
            _check_roi_reachable(state, profile, calib_status_var)
            _rebuild_plan()
        state["drag_start_disp"] = None

    def _on_right_click(ev):
        """Click derecho: eliminar el punto de click más cercano."""
        if state["plan_mode"] != "clicks" or not state["click_points"]:
            return
        px, py = _disp_to_img(ev.x, ev.y, state)
        if px is None:
            return
        pts = state["click_points"]
        dists = [(i, (p[0]-px)**2 + (p[1]-py)**2) for i, p in enumerate(pts)]
        closest_idx = min(dists, key=lambda x: x[1])[0]
        if dists[closest_idx][1] < 40**2:  # 40px de tolerancia
            pts.pop(closest_idx)
            _rebuild_plan()

    img_canvas.bind("<ButtonPress-1>", _on_press)
    img_canvas.bind("<B1-Motion>", _on_drag)
    img_canvas.bind("<ButtonRelease-1>", _on_release)
    img_canvas.bind("<Button-3>", _on_right_click)

    # ── Cierre ───────────────────────────────────────────────────────────────
    def _close():
        state["alive"] = False
        if on_close_cb:
            try: on_close_cb()
            except Exception: pass
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", _close)


    win.after(100, _update_display)


# ---------------------------------------------------------------------------
# Jog panel — profile-aware
# ---------------------------------------------------------------------------

def _build_jog_panel(parent, stage, profile, win):
    import tkinter as tk
    import threading

    jf = tk.LabelFrame(parent,
                       text="Mover muestra — %s" % profile.stage_driver.upper(),
                       padx=6, pady=4)
    jf.pack(fill="x", padx=6, pady=(6, 2))

    # Label de error visible (no más excepciones silenciosas)
    jog_status = tk.StringVar(value="")
    tk.Label(jf, textvariable=jog_status, fg="#b71c1c",
             font=("", 7), wraplength=255, anchor="w").pack(fill="x")

    # v_step ANTES del loop para que los lambdas de los botones lo capturen correctamente
    v_step = tk.StringVar(value=str(profile.jog_step_default_mm))

    pos_vars = {}

    def _do_jog(axis, delta):
        try:
            win.after(0, lambda: jog_status.set(""))
            stage.move_rel(axis, delta)
            try:
                val = stage.position(axis)
                win.after(0, lambda v=val, a=axis: pos_vars[a].set("%.4f" % v))
            except Exception:
                pass
        except Exception as e:
            msg = "Error jog %s: %s" % (axis.upper(), str(e)[:80])
            win.after(0, lambda m=msg: jog_status.set(m))

    for ax in profile.axes:
        row = tk.Frame(jf); row.pack(fill="x", pady=1)
        tk.Label(row, text=ax.upper() + ":", width=3, anchor="w").pack(side="left")
        pv = tk.StringVar(value="—")
        tk.Label(row, textvariable=pv, width=9, anchor="e",
                 relief="sunken", bg="#f0f0f0").pack(side="left", padx=2)
        tk.Label(row, text="mm").pack(side="left")

        # Captura ax por default arg — fix del clásico bug de cierre en loop
        tk.Button(row, text="-", width=3, font=("", 9, "bold"),
                  command=lambda a=ax: threading.Thread(
                      target=lambda: _do_jog(a, -float(v_step.get().replace(",", "."))),
                      daemon=True).start()
                  ).pack(side="right")
        tk.Button(row, text="+", width=3, font=("", 9, "bold"),
                  command=lambda a=ax: threading.Thread(
                      target=lambda: _do_jog(a, +float(v_step.get().replace(",", "."))),
                      daemon=True).start()
                  ).pack(side="right", padx=(0, 2))

        pos_vars[ax] = pv

    # Paso de jog
    step_row = tk.Frame(jf); step_row.pack(fill="x", pady=(4, 2))
    tk.Label(step_row, text="Paso (mm):").pack(side="left")
    tk.Entry(step_row, textvariable=v_step, width=8).pack(side="left", padx=4)

    # Botones de paso rápido
    preset_row = tk.Frame(jf); preset_row.pack(fill="x")
    for label, val in [("fino", profile.jog_step_fine_mm),
                       ("def",  profile.jog_step_default_mm),
                       ("grueso", profile.jog_step_coarse_mm)]:
        def _set_step(v=val):
            v_step.set(str(v))
        tk.Button(preset_row, text=label, width=6, font=("", 8),
                  command=_set_step).pack(side="left", padx=1)

    # Homing
    home_axes = [ax for ax in profile.axes if profile.homing_available(ax)]
    if home_axes:
        home_row = tk.Frame(jf); home_row.pack(fill="x", pady=(4, 0))
        for ax in home_axes:
            def _do_home(a=ax):
                win.after(0, lambda: jog_status.set("Homing %s..." % a.upper()))
                def _t(axis=a):
                    try:
                        stage.home(axis)
                        try:
                            val = stage.position(axis)
                            win.after(0, lambda v=val, ax2=axis: pos_vars[ax2].set("%.4f" % v))
                        except Exception: pass
                        win.after(0, lambda: jog_status.set("Home %s OK" % axis.upper()))
                    except Exception as e:
                        msg = "Error Home %s: %s" % (axis.upper(), str(e)[:80])
                        win.after(0, lambda m=msg: jog_status.set(m))
                threading.Thread(target=_t, daemon=True).start()
            tk.Button(home_row, text="Home %s" % ax.upper(), width=9, font=("", 8),
                      command=_do_home).pack(side="left", padx=2)

    # Actualizar posiciones periódicamente
    def _poll_pos():
        if not win.winfo_exists():
            return
        for ax in profile.axes:
            try:
                pos_vars[ax].set("%.4f" % stage.position(ax))
            except Exception:
                pass
        win.after(500, _poll_pos)

    win.after(200, _poll_pos)

    # Rangos de referencia
    range_txt = "  ".join(profile.range_label(ax) for ax in profile.axes
                          if ax in profile.range_mm)
    if range_txt:
        tk.Label(jf, text=range_txt, fg="#888", font=("", 7),
                 wraplength=260).pack(anchor="w", pady=(2, 0))


# ---------------------------------------------------------------------------
# Plan panel — 3 modos
# ---------------------------------------------------------------------------

def _build_plan_panel(parent, state, profile, win, img_canvas,
                      scan_plan_path, session_dir, save_dir, base_name,
                      get_cam_label):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    pf = tk.LabelFrame(parent, text="Plan de scan", padx=4, pady=4)
    pf.pack(fill="both", expand=True, padx=6, pady=(2, 6))

    nb = ttk.Notebook(pf)
    nb.pack(fill="x")

    tab_cl  = tk.Frame(nb, pady=4)
    tab_gr  = tk.Frame(nb, pady=4)
    tab_csv = tk.Frame(nb, pady=4)
    tab_prev = tk.Frame(nb, pady=4)
    nb.add(tab_cl,   text=" Clicks ")
    nb.add(tab_gr,   text=" Grilla ")
    nb.add(tab_csv,  text="  CSV  ")
    nb.add(tab_prev, text=" Sesión ant. ")

    def _on_tab_change(ev):
        tabs = ["clicks", "grid", "csv", "prev_session"]
        state["plan_mode"] = tabs[nb.index(nb.select())]

    nb.bind("<<NotebookTabChanged>>", _on_tab_change)

    # ── Tab CLICKS ──────────────────────────────────────────────────────────
    tk.Label(tab_cl, text="Click sobre la imagen para agregar puntos.\n"
             "Click derecho para eliminar el más cercano.",
             font=("", 8), fg="#555", justify="left").pack(anchor="w", padx=4)

    cl_btn_row = tk.Frame(tab_cl); cl_btn_row.pack(fill="x", pady=2)
    tk.Button(cl_btn_row, text="↩ Deshacer último", font=("", 8),
              command=lambda: _undo_click(state)).pack(side="left", padx=2)
    tk.Button(cl_btn_row, text="🗑 Limpiar todos", font=("", 8),
              command=lambda: _clear_clicks(state)).pack(side="left", padx=2)

    # ── Tab GRILLA ──────────────────────────────────────────────────────────
    tk.Label(tab_gr, text="Genera una grilla dentro del ROI.",
             font=("", 8), fg="#555").pack(anchor="w", padx=4)

    gr_fields = tk.Frame(tab_gr); gr_fields.pack(fill="x", padx=4)

    tk.Label(gr_fields, text="Paso X (mm):").grid(row=0, column=0, sticky="w")
    v_stepx = tk.StringVar(value="0.2")
    tk.Entry(gr_fields, textvariable=v_stepx, width=7).grid(row=0, column=1, padx=4)

    tk.Label(gr_fields, text="Paso Y (mm):").grid(row=1, column=0, sticky="w")
    v_stepy = tk.StringVar(value="0.2")
    tk.Entry(gr_fields, textvariable=v_stepy, width=7).grid(row=1, column=1, padx=4)

    v_serp = tk.IntVar(value=1)
    tk.Checkbutton(gr_fields, text="Serpentina", variable=v_serp).grid(
        row=2, column=0, columnspan=2, sticky="w")

    tk.Label(gr_fields, text="Origen:").grid(row=3, column=0, sticky="w")
    v_origin = tk.StringVar(value="roi_tl")
    origin_opts = [("Esq. sup. izq. del ROI", "roi_tl"),
                   ("Centro del ROI", "roi_center"),
                   ("Posición actual stage", "stage_pos")]
    for i, (lbl, val) in enumerate(origin_opts):
        tk.Radiobutton(gr_fields, text=lbl, variable=v_origin, value=val,
                       font=("", 8)).grid(row=4+i, column=0, columnspan=2, sticky="w")

    def _preview_grid():
        # ── Validar ROI obligatorio ──────────────────────────────────────────
        if state.get("roi") is None:
            messagebox.showwarning(
                "ROI no definido",
                "Primero definí el área de scan arrastrando sobre la imagen.\n\n"
                "El ROI delimita la zona donde se generarán los puntos.\n"
                "Sin ROI la grilla no puede generarse correctamente.",
                parent=win)
            return

        if state.get("calibration") is None or not state["calibration"].valid:
            messagebox.showwarning(
                "Sin calibración",
                "Necesitás calibrar la imagen antes de generar la grilla.\n\n"
                "Usá el botón '🔧 Calibrar...' en la parte superior.",
                parent=win)
            return

        try:
            sx = float(v_stepx.get().replace(",", "."))
            sy = float(v_stepy.get().replace(",", "."))
            if sx <= 0 or sy <= 0:
                raise ValueError("pasos deben ser > 0")
        except ValueError as e:
            messagebox.showerror("Paso inválido", str(e), parent=win)
            return

        pts = _generate_grid(state, profile, sx, sy,
                             bool(v_serp.get()), v_origin.get())
        if not pts:
            messagebox.showwarning(
                "Grilla vacía",
                "No se generaron puntos.\n\n"
                "Verificá:\n"
                "• El ROI tenga un área razonable\n"
                "• Los pasos X/Y sean menores al tamaño del ROI\n"
                "• El ROI esté dentro del rango del stage\n\n"
                "Rango del stage: %s" % (
                    "  ".join(profile.range_label(ax) for ax in profile.axes
                              if ax in profile.range_mm)
                    if hasattr(profile, "range_mm") else "desconocido"),
                parent=win)
            return
        state["plan_points"] = pts
        state["plan_mode"] = "grid"
        _update_plan_listbox()
        messagebox.showinfo("Grilla generada",
                            "%d puntos en la grilla.\n"
                            "Verificalos en la imagen y exportá el plan cuando estés listo."
                            % len(pts), parent=win)

    tk.Button(tab_gr, text="⟳ Generar grilla", bg="#1565c0", fg="white",
              command=_preview_grid).pack(pady=4, padx=4, anchor="w")

    # ── Tab CSV ─────────────────────────────────────────────────────────────
    tk.Label(tab_csv,
             text="CSV con columnas: x_mm,y_mm  ó  px,py\n"
                  "La primera fila puede ser encabezado.",
             font=("", 8), fg="#555", justify="left").pack(anchor="w", padx=4)

    csv_status = tk.StringVar(value="Sin archivo cargado")
    tk.Label(tab_csv, textvariable=csv_status, fg="#555", font=("", 8),
             wraplength=240).pack(anchor="w", padx=4)

    def _load_csv():
        path = filedialog.askopenfilename(
            title="Cargar coordenadas",
            filetypes=[("CSV", "*.csv *.txt"), ("Todos", "*.*")])
        if not path:
            return
        try:
            pts = _parse_csv(path, state)
            if not pts:
                csv_status.set("⚠  No se encontraron puntos válidos en el CSV.")
                return
            state["plan_points"] = pts
            state["plan_mode"] = "csv"
            csv_status.set("✅  %d puntos cargados desde %s" % (len(pts), os.path.basename(path)))
            _update_plan_listbox()
        except Exception as e:
            messagebox.showerror("CSV", "Error al leer el archivo:\n%s" % e, parent=win)

    tk.Button(tab_csv, text="📂 Abrir CSV...", command=_load_csv).pack(
        pady=4, padx=4, anchor="w")

    # ── Tab SESIÓN ANTERIOR ──────────────────────────────────────────────────
    tk.Label(tab_prev,
             text="Reutiliza puntos de un scan anterior.\n"
                  "Buscá la carpeta de sesión o un scan_plan.json.",
             font=("", 8), fg="#555", justify="left").pack(anchor="w", padx=4)

    prev_status = tk.StringVar(value="Sin sesión cargada.")
    tk.Label(tab_prev, textvariable=prev_status, fg="#1a6a1a",
             font=("", 8), wraplength=260, justify="left").pack(anchor="w", padx=4)

    def _load_prev_session():
        """Busca un scan_plan.json de una sesión anterior."""
        # Primero intentar directamente archivo JSON
        path = filedialog.askopenfilename(
            title="Seleccioná un scan_plan.json anterior",
            initialdir=os.path.dirname(session_dir) if os.path.isdir(
                os.path.dirname(session_dir)) else os.path.expanduser("~"),
            filetypes=[("JSON plan", "scan_plan.json *.json"), ("Todos", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            pts = data.get("points") or []
            if not pts:
                prev_status.set("⚠  El archivo no tiene puntos.")
                return
            # Copiar puntos al estado actual
            state["plan_points"] = [dict(p) for p in pts]
            state["plan_mode"] = "prev_session"
            prev_status.set("✅  %d puntos desde:\n%s" % (
                len(pts), os.path.basename(os.path.dirname(path)) +
                "/" + os.path.basename(path)))
            _update_plan_listbox()
        except Exception as e:
            messagebox.showerror("Sesión anterior",
                                 "No se pudo leer el archivo:\n%s" % e, parent=win)

    def _browse_session_folder():
        """Busca la carpeta de sesión y carga su scan_plan.json."""
        folder = filedialog.askdirectory(
            title="Seleccioná la carpeta de sesión anterior",
            initialdir=os.path.dirname(session_dir) if os.path.isdir(
                os.path.dirname(session_dir)) else os.path.expanduser("~"),
        )
        if not folder:
            return
        plan_path = os.path.join(folder, "scan_plan.json")
        if not os.path.isfile(plan_path):
            # Buscar un nivel arriba
            for fname in os.listdir(folder):
                candidate = os.path.join(folder, fname, "scan_plan.json")
                if os.path.isfile(candidate):
                    plan_path = candidate
                    break
        if not os.path.isfile(plan_path):
            messagebox.showwarning("Sesión anterior",
                "No se encontró scan_plan.json en esa carpeta.\n"
                "Buscá directamente el archivo con 'Abrir JSON...'",
                parent=win)
            return
        try:
            with open(plan_path, encoding="utf-8") as f:
                data = json.load(f)
            pts = data.get("points") or []
            if not pts:
                prev_status.set("⚠  El plan no tiene puntos.")
                return
            state["plan_points"] = [dict(p) for p in pts]
            state["plan_mode"] = "prev_session"
            prev_status.set("✅  %d puntos desde:\n%s" % (
                len(pts), os.path.relpath(plan_path,
                    os.path.dirname(os.path.dirname(session_dir)))))
            _update_plan_listbox()
        except Exception as e:
            messagebox.showerror("Sesión anterior",
                                 "Error al leer:\n%s" % e, parent=win)

    prev_btn_row = tk.Frame(tab_prev)
    prev_btn_row.pack(fill="x", pady=4, padx=4)
    tk.Button(prev_btn_row, text="📁 Carpeta de sesión…",
              command=_browse_session_folder).pack(side="left", padx=(0, 4))
    tk.Button(prev_btn_row, text="📄 Abrir JSON…",
              command=_load_prev_session).pack(side="left")

    # ── Lista de puntos ──────────────────────────────────────────────────────
    tk.Label(pf, text="Puntos del plan:", font=("", 8, "bold")).pack(anchor="w", padx=4)

    list_frame = tk.Frame(pf)
    list_frame.pack(fill="both", expand=True, padx=4)

    listbox = tk.Listbox(list_frame, font=("Courier", 7), height=8,
                         selectmode=tk.SINGLE, activestyle="none")
    scroll = tk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
    listbox.configure(yscrollcommand=scroll.set)
    listbox.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    state["_listbox"] = listbox
    count_var = tk.StringVar(value="0 puntos")
    tk.Label(pf, textvariable=count_var, font=("", 8), fg="#555").pack(
        anchor="w", padx=4)
    state["_count_var"] = count_var

    # ── Exportar / Limpiar ───────────────────────────────────────────────────
    btn_row = tk.Frame(pf); btn_row.pack(fill="x", padx=4, pady=4)

    def _export_plan():
        pts = state["plan_points"]
        if not pts:
            messagebox.showwarning("Plan vacío",
                "No hay puntos en el plan.\n"
                "Agrega puntos con cualquier modo.", parent=win)
            return
        # Numeración final
        numbered = [dict(i=idx+1, **p) for idx, p in enumerate(pts)]
        plan_data = {
            "version":       2,
            "stage_driver":  profile.stage_driver,
            "camera_label":  get_cam_label(),
            "n_points":      len(numbered),
            "mode":          state["plan_mode"],
            "roi":           state["roi"],
            "points":        numbered,
        }
        try:
            safe_write_json(scan_plan_path, plan_data)
            messagebox.showinfo("Plan exportado",
                "%d puntos guardados en:\n%s" % (len(numbered), scan_plan_path),
                parent=win)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=win)

    def _clear_all():
        state["click_points"] = []
        state["plan_points"]  = []
        _update_plan_listbox()

    tk.Button(btn_row, text="💾 Exportar plan", bg="#2e7d32", fg="white",
              font=("", 9), command=_export_plan).pack(side="left", padx=(0, 4))
    tk.Button(btn_row, text="🗑 Limpiar", font=("", 9),
              command=_clear_all).pack(side="left")



# ---------------------------------------------------------------------------
# Redibujado del canvas
# ---------------------------------------------------------------------------

def _redraw_canvas(img_canvas, state, _imref, profile):
    from PIL import Image, ImageTk
    import tkinter as tk

    frame = state["last_bgr"]
    if frame is None:
        return

    H, W = frame.shape[:2]
    win = img_canvas.winfo_toplevel()
    if not win.winfo_exists():
        return
    img_canvas.update_idletasks()
    cw = img_canvas.winfo_width()
    ch = img_canvas.winfo_height()
    if cw < 50 or ch < 50:
        return

    scale = min(cw / W, ch / H)
    dw, dh = int(W * scale), int(H * scale)
    offx = (cw - dw) // 2
    offy = (ch - dh) // 2
    state["disp_scale"] = scale
    state["disp_w"] = dw
    state["disp_h"] = dh
    state["disp_offx"] = offx
    state["disp_offy"] = offy

    disp = cv2.cvtColor(
        cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_AREA),
        cv2.COLOR_BGR2RGB)

    # ROI
    roi = state.get("roi")
    if roi:
        x1, y1, x2, y2 = [int(v * scale) for v in roi]
        cv2.rectangle(disp, (x1, y1), (x2, y2), (0, 255, 150), 2)

    # Drag en curso
    if state.get("dragging") and state.get("drag_start_disp") and state.get("drag_curr_disp"):
        sx, sy = state["drag_start_disp"]
        cx, cy = state["drag_curr_disp"]
        dx1, dy1 = sx - offx, sy - offy
        dx2, dy2 = cx - offx, cy - offy
        cv2.rectangle(disp, (dx1, dy1), (dx2, dy2), (255, 200, 0), 1)

    # ── Overlay de ejes cartesianos ──────────────────────────────────────────
    # Usa la INVERSA de la matriz afín para obtener la DIRECCIÓN de cada eje
    # en espacio de display. Las flechas tienen longitud fija (20% de la imagen)
    # sin importar la escala real o el rango del stage.
    cal = state.get("calibration")
    if cal and cal.valid:
        try:
            import numpy as np, math

            A     = np.array(cal.A, dtype=float)   # mm = A @ px + t
            t_vec = np.array(cal.t, dtype=float)
            A_inv = np.linalg.inv(A)               # px = A_inv @ (mm - t)

            # Longitud de flecha = 22% del lado menor de la imagen display
            arrow_len = max(50, int(min(dw, dh) * 0.22))

            # Vectores de dirección normalizada en px para cada eje mm
            # columna 0 de A_inv: cuántos px se mueven por 1mm en +X del stage
            # columna 1 de A_inv: cuántos px se mueven por 1mm en +Y del stage
            dir_x = A_inv[:, 0]
            dir_y = A_inv[:, 1]
            norm_x = np.linalg.norm(dir_x)
            norm_y = np.linalg.norm(dir_y)
            if norm_x < 1e-9 or norm_y < 1e-9:
                raise ValueError("singular")

            ux = (dir_x / norm_x * arrow_len)   # vector unidad +X en px, longitud fija
            uy = (dir_y / norm_y * arrow_len)   # vector unidad +Y en px, longitud fija

            # Origen en display: A_inv @ (0,0 − t) * scale
            o_px = A_inv @ (-t_vec)
            ox_f = float(o_px[0]) * scale
            oy_f = float(o_px[1]) * scale

            # Si origen está dentro de la imagen mostrar allí; si no, anclar en esquina
            MARGIN = arrow_len + 20
            if 0 <= ox_f < dw and 0 <= oy_f < dh:
                ox, oy = int(ox_f), int(oy_f)
                origin_in_img = True
            else:
                ox = MARGIN
                oy = dh - MARGIN
                origin_in_img = False

            # Escala de display para las flechas (no afecta a la dirección)
            ux_d = (ux * scale).astype(int)
            uy_d = (uy * scale).astype(int)

            # ── Flecha +X (azul) ────────────────────────────────────────────
            ex, ey = ox + int(ux_d[0]), oy + int(ux_d[1])
            cv2.arrowedLine(disp, (ox, oy), (ex, ey), (255, 100, 60), 2, tipLength=0.20)
            lbl_off = (5, -5) if ex >= ox else (-35, -5)
            cv2.putText(disp, "+X", (ex + lbl_off[0], ey + lbl_off[1]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 130, 80), 1)

            # ── Flecha +Y (verde) ────────────────────────────────────────────
            fy, gy = ox + int(uy_d[0]), oy + int(uy_d[1])
            cv2.arrowedLine(disp, (ox, oy), (fy, gy), (60, 220, 60), 2, tipLength=0.20)
            lbl_off2 = (5, -5) if fy >= ox else (-35, -5)
            cv2.putText(disp, "+Y", (fy + lbl_off2[0], gy + lbl_off2[1]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (80, 230, 80), 1)

            # ── Origen ───────────────────────────────────────────────────────
            if origin_in_img:
                cv2.circle(disp, (ox, oy), 7, (0, 165, 255), -1)
                cv2.circle(disp, (ox, oy), 7, (255, 255, 255), 1)
                cv2.putText(disp, "(0,0)", (ox + 9, oy + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.33, (255, 200, 80), 1)
            else:
                cv2.circle(disp, (ox, oy), 5, (160, 160, 160), -1)

            # ── Ángulo de rotación y advertencia de calibración ──────────────
            rot = math.degrees(math.atan2(float(A[0][1]), float(A[0][0])))
            sx  = math.sqrt(float(A[0][0])**2 + float(A[0][1])**2)
            sy  = math.sqrt(float(A[1][0])**2 + float(A[1][1])**2)
            ratio = max(sx, sy) / max(min(sx, sy), 1e-12)

            suspicious = abs(rot) > 20.0 or ratio > 2.5

            # Texto con ángulo, siempre visible
            rot_txt = "rot %.1f°  sx/sy=%.2f" % (rot, ratio)
            txt_col = (0, 100, 255) if not suspicious else (0, 0, 220)
            cv2.putText(disp, rot_txt, (6, dh - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.33, txt_col, 1)

            # Si sospechoso: banner rojo de advertencia
            if suspicious:
                warn1 = "⚠ CALIBRACION SOSPECHOSA"
                warn2 = "rot=%.1f° (esperado<20°)  escala X/Y=%.1fx" % (rot, ratio)
                cv2.rectangle(disp, (4, 4), (dw - 4, 44), (0, 0, 180), -1)
                cv2.putText(disp, warn1, (8, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 100), 1)
                cv2.putText(disp, warn2, (8, 38),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.32, (200, 200, 255), 1)

        except Exception:
            pass


    # Puntos del plan
    pts = state.get("plan_points", [])
    for idx, p in enumerate(pts):
        px, py = p.get("px"), p.get("py")
        if px is None or py is None:
            continue
        xd, yd = int(px * scale), int(py * scale)
        cv2.circle(disp, (xd, yd), 7, (0, 200, 255), -1)
        cv2.circle(disp, (xd, yd), 7, (0, 80, 180), 1)
        cv2.putText(disp, str(idx + 1), (xd + 6, yd - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)

    # Puntos de click (modo clicks, antes de commit al plan)
    for px, py in state.get("click_points", []):
        xd, yd = int(px * scale), int(py * scale)
        cv2.drawMarker(disp, (xd, yd), (255, 120, 0),
                       cv2.MARKER_CROSS, 16, 2)

    # ── Focus Assist overlay ──────────────────────────────────────────────────
    _draw_focus_overlay(disp, state, dw, dh, scale, frame)

    full = Image.new("RGB", (cw, ch), (17, 17, 17))
    full.paste(Image.fromarray(disp), (offx, offy))
    imgtk = ImageTk.PhotoImage(full)
    _imref[0] = imgtk
    img_canvas.delete("all")
    img_canvas.create_image(0, 0, anchor="nw", image=imgtk)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _disp_to_img(xd, yd, state):
    """Convierte coordenadas de display a coordenadas de imagen original."""
    scale = state.get("disp_scale", 1.0)
    offx  = state.get("disp_offx", 0)
    offy  = state.get("disp_offy", 0)
    dw    = state.get("disp_w")
    dh    = state.get("disp_h")
    bgr   = state.get("last_bgr")
    if bgr is None or scale == 0:
        return None, None
    H, W = bgr.shape[:2]
    ix = int(round((xd - offx) / scale))
    iy = int(round((yd - offy) / scale))
    if 0 <= ix < W and 0 <= iy < H:
        return ix, iy
    return None, None


def _undo_click(state):
    if state["click_points"]:
        state["click_points"].pop()
    _rebuild_from_state(state)


def _clear_clicks(state):
    state["click_points"] = []
    _rebuild_from_state(state)


def _rebuild_from_state(state):
    rb = state.get("_rebuild_plan")
    if rb:
        rb()


def _update_plan_listbox():
    """Wrapper global — se llama desde dentro del panel."""
    pass  # implementado dentro de _build_plan_panel a través de state


def _check_roi_reachable(state, profile, calib_status_var):
    """Advierte si el ROI en mm excede el rango del stage."""
    roi = state.get("roi")
    cal = state.get("calibration")
    if roi is None or cal is None or not cal.valid:
        return
    x1, y1, x2, y2 = roi
    corners = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
    out = []
    for px, py in corners:
        try:
            xm, ym = cal.px_to_mm(px, py)
            if not profile.can_reach(xm, ym):
                out.append((xm, ym))
        except Exception:
            pass
    if out:
        calib_status_var.set(
            "⚠  ROI parcialmente fuera del rango del stage "
            "(%d esquinas inalcanzables)" % len(out))


def _generate_grid(state, profile, step_x_mm, step_y_mm,
                   serpentine, origin_mode):
    """
    Genera puntos de grilla en mm dentro del ROI.

    Requisitos (verificados antes de llamar desde _preview_grid):
      - ROI definido
      - Calibración válida

    Los puntos se filtran con profile.can_reach() para garantizar que
    ningún punto esté fuera del rango físico del stage.
    """
    import math
    cal = state.get("calibration")
    roi = state.get("roi")

    # Ambos son obligatorios (se validan en _preview_grid, pero doble check)
    if cal is None or not cal.valid:
        return []
    if roi is None:
        return []

    x1p, y1p, x2p, y2p = roi

    # Convertir las 4 esquinas del ROI a mm (la calibración puede tener rotación)
    corners_px = [(x1p, y1p), (x2p, y1p), (x1p, y2p), (x2p, y2p)]
    corners_mm = []
    for cpx, cpy in corners_px:
        try:
            xm, ym = cal.px_to_mm(cpx, cpy)
            corners_mm.append((xm, ym))
        except Exception:
            return []

    xmm_min = min(c[0] for c in corners_mm)
    xmm_max = max(c[0] for c in corners_mm)
    ymm_min = min(c[1] for c in corners_mm)
    ymm_max = max(c[1] for c in corners_mm)

    # Intersectar con el rango físico del stage
    if hasattr(profile, "range_mm") and profile.range_mm:
        xr = profile.range_mm.get("x")
        yr = profile.range_mm.get("y")
        if xr:
            xmm_min = max(xmm_min, xr[0])
            xmm_max = min(xmm_max, xr[1])
        if yr:
            ymm_min = max(ymm_min, yr[0])
            ymm_max = min(ymm_max, yr[1])

    # Verificar que el área sea positiva después del clampeo
    if xmm_max <= xmm_min or ymm_max <= ymm_min:
        return []

    # Generar coordenadas según origen
    if origin_mode == "roi_center":
        cx = (xmm_min + xmm_max) / 2.0
        cy = (ymm_min + ymm_max) / 2.0
        nx = int(math.floor((xmm_max - xmm_min) / step_x_mm / 2)) + 1
        ny = int(math.floor((ymm_max - ymm_min) / step_y_mm / 2)) + 1
        xs = [cx + i * step_x_mm for i in range(-nx, nx + 1)
              if xmm_min <= cx + i * step_x_mm <= xmm_max]
        ys = [cy + j * step_y_mm for j in range(-ny, ny + 1)
              if ymm_min <= cy + j * step_y_mm <= ymm_max]
    else:  # roi_tl (y stage_pos como fallback)
        xs = _linspace(xmm_min, xmm_max, step_x_mm)
        ys = _linspace(ymm_min, ymm_max, step_y_mm)

    if not xs or not ys:
        return []

    pts = []
    for j, ym in enumerate(ys):
        row_xs = xs if (not serpentine or j % 2 == 0) else list(reversed(xs))
        for xm in row_xs:
            # Verificación final contra rango del stage
            if not profile.can_reach(xm, ym):
                continue
            try:
                px, py = _mm_to_px(cal, xm, ym)
            except Exception:
                px, py = 0, 0
            pts.append({"px": int(px), "py": int(py),
                        "x_mm": round(xm, 6), "y_mm": round(ym, 6)})

    return pts


def _mm_to_px(cal, x_mm, y_mm):
    """Transforma (x_mm, y_mm) → (px, py) invirtiendo la transformación afín."""
    import numpy as np
    A = np.array(cal.A, dtype=float)
    t = np.array(cal.t, dtype=float)
    b = np.array([x_mm, y_mm]) - t
    sol = np.linalg.solve(A, b)
    return float(sol[0]), float(sol[1])


def _linspace(start, stop, step):
    if step <= 0 or stop < start:
        return []
    pts = []
    x = start
    while x <= stop + 1e-9:
        pts.append(round(x, 9))
        x += step
    return pts


def _parse_csv(path, state):
    """Lee un CSV con columnas x_mm,y_mm  ó  px,py."""
    cal = state.get("calibration")
    pts = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        # Detectar separador
        sample = f.read(2048)
        f.seek(0)
        sep = "," if sample.count(",") >= sample.count(";") else ";"
        reader = csv.DictReader(f, delimiter=sep)

        # Normalizar nombres de columna
        def _norm(s):
            return s.strip().lower().replace(" ", "")

        for row in reader:
            rn = {_norm(k): v.strip() for k, v in row.items()}

            if "x_mm" in rn and "y_mm" in rn:
                try:
                    xm = float(rn["x_mm"].replace(",", "."))
                    ym = float(rn["y_mm"].replace(",", "."))
                    pt = {"x_mm": round(xm, 6), "y_mm": round(ym, 6)}
                    if cal and cal.valid:
                        try:
                            px, py = _mm_to_px(cal, xm, ym)
                            pt["px"] = int(px)
                            pt["py"] = int(py)
                        except Exception:
                            pt["px"] = 0; pt["py"] = 0
                    else:
                        pt["px"] = 0; pt["py"] = 0
                    pts.append(pt)
                except ValueError:
                    pass

            elif "px" in rn and "py" in rn:
                try:
                    px = int(float(rn["px"]))
                    py = int(float(rn["py"]))
                    pt = {"px": px, "py": py}
                    if cal and cal.valid:
                        try:
                            xm, ym = cal.px_to_mm(px, py)
                            pt["x_mm"] = round(xm, 6)
                            pt["y_mm"] = round(ym, 6)
                        except Exception:
                            pass
                    pts.append(pt)
                except ValueError:
                    pass

    return pts


# ---------------------------------------------------------------------------
# Focus Assist — thread, panel UI, overlay
# ---------------------------------------------------------------------------

def _focus_assist_loop(state: dict, mask) -> None:
    """
    Calcula sharpness_score a ~5 Hz sobre la ROI posicionable del último frame.
    Corre como daemon thread; no lanza excepciones hacia afuera.
    Si focus_assist['enabled'] es False duerme el intervalo sin computar nada.

    La máscara de píxeles muertos se recorta al mismo patch que la ROI y se
    pasa directamente a sharpness_score, que excluye esos píxeles (y sus
    vecinos inmediatos) del cálculo de la varianza del Laplaciano.
    """
    from service.calibration_service import sharpness_score as _sharpness

    INTERVAL = 0.20   # 5 Hz

    while state.get("alive", True):
        fa = state.get("focus_assist", {})
        if fa.get("enabled"):
            frame = state.get("last_bgr")
            if frame is None:
                fa["error"] = "sin stream — no hay frames de cámara"
            else:
                try:
                    H_f, W_f = frame.shape[:2]
                    frac     = float(fa.get("roi_frac",    0.40))
                    cx_frac  = float(fa.get("roi_cx_frac", 0.28))
                    cy_frac  = float(fa.get("roi_cy_frac", 0.25))

                    h2 = max(1, int(H_f * frac / 2))
                    w2 = max(1, int(W_f * frac / 2))
                    # Centro del ROI, clampeado para no salirse de la imagen
                    cx = max(w2, min(W_f - w2, int(W_f * cx_frac)))
                    cy = max(h2, min(H_f - h2, int(H_f * cy_frac)))

                    crop = frame[cy - h2: cy + h2, cx - w2: cx + w2]
                    gray = (cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                            if crop.ndim == 3 else crop.copy())

                    # Recortar la máscara al mismo patch y pasarla a sharpness_score.
                    # sharpness_score excluye los píxeles muertos (+ vecinos 3×3)
                    # del cálculo de la varianza, sin modificar la imagen.
                    mask_crop = (mask[cy - h2: cy + h2, cx - w2: cx + w2]
                                 if mask is not None else None)

                    score = _sharpness(gray, mask_crop)
                    fa["score"] = score
                    fa["error"] = None
                    if fa.get("max_score") is None or score > fa["max_score"]:
                        fa["max_score"] = score

                except Exception as exc:
                    fa["error"] = repr(exc)[:80]

        time.sleep(INTERVAL)


def _build_focus_assist_panel(parent, state: dict, win) -> None:
    """Panel de Focus Assist en el right_panel del preview."""
    import tkinter as tk

    ff = tk.LabelFrame(parent, text="Focus Assist", padx=6, pady=4)
    ff.pack(fill="x", padx=6, pady=(2, 6))

    v_enabled = tk.BooleanVar(value=False)

    def _toggle():
        enabled = v_enabled.get()
        fa = state["focus_assist"]
        fa["enabled"] = enabled
        if not enabled:
            fa["score"] = None
            fa["error"] = None

    tk.Checkbutton(ff, text="Activar (5 Hz, ROI 40%)",
                   variable=v_enabled, command=_toggle,
                   font=("", 8)).pack(anchor="w")

    # ── Selector de posición del ROI ──────────────────────────────────────────
    pos_row = tk.Frame(ff)
    pos_row.pack(fill="x", pady=(1, 0))
    tk.Label(pos_row, text="ROI:", font=("", 7), fg="#888").pack(side="left")

    # (símbolo, cx_frac, cy_frac, tooltip)
    _POSITIONS = [
        ("↖", 0.28, 0.25),
        ("↗", 0.72, 0.25),
        ("⊙", 0.50, 0.50),
        ("↙", 0.28, 0.75),
        ("↘", 0.72, 0.75),
    ]
    for sym, cx, cy in _POSITIONS:
        def _set(cx=cx, cy=cy):
            state["focus_assist"]["roi_cx_frac"] = cx
            state["focus_assist"]["roi_cy_frac"] = cy
            state["focus_assist"]["max_score"]   = None   # reset al mover ROI
        tk.Button(pos_row, text=sym, width=2, font=("", 9),
                  command=_set).pack(side="left", padx=1)

    # Número grande
    v_score_txt = tk.StringVar(value="—")
    score_label = tk.Label(ff, textvariable=v_score_txt,
                           font=("Courier", 20, "bold"), fg="#22dd66",
                           anchor="e", bg="#1a1a1a")
    score_label.pack(fill="x", padx=2)

    # Barra de progreso (canvas simple)
    BAR_W, BAR_H = 238, 10
    bar_cv = tk.Canvas(ff, width=BAR_W, height=BAR_H,
                       bg="#2a2a2a", highlightthickness=0)
    bar_cv.pack(anchor="w", pady=(1, 2))

    # Máximo histórico
    v_max_txt = tk.StringVar(value="mejor: —")
    tk.Label(ff, textvariable=v_max_txt, font=("Courier", 8),
             fg="#888888", anchor="w").pack(fill="x")

    def _reset_max():
        state["focus_assist"]["max_score"] = None

    tk.Button(ff, text="Reset max", font=("", 8),
              command=_reset_max).pack(anchor="w", pady=(2, 0))

    def _redraw_bar(frac: float, color: str) -> None:
        bar_cv.delete("all")
        bar_cv.create_rectangle(0, 0, BAR_W, BAR_H, fill="#333333", outline="")
        if frac > 0:
            bar_cv.create_rectangle(0, 0, int(BAR_W * frac), BAR_H,
                                    fill=color, outline="")

    def _poll() -> None:
        if not win.winfo_exists():
            return
        fa = state.get("focus_assist", {})
        if fa.get("enabled"):
            score = fa.get("score")
            max_s = fa.get("max_score")
            err   = fa.get("error")

            if err:
                v_score_txt.set("ERR")
                score_label.configure(fg="#ff4444")
                v_max_txt.set(err[:38])
                _redraw_bar(0, "#ff4444")
            elif score is not None:
                frac  = min(1.0, score / max(max_s, 1.0)) if max_s else 0.5
                color = "#22dd66" if frac > 0.8 else ("#ffdd00" if frac > 0.5 else "#ee4444")
                v_score_txt.set("%.0f" % score)
                score_label.configure(fg=color)
                v_max_txt.set("mejor: %.0f" % max_s if max_s is not None else "mejor: —")
                _redraw_bar(frac, color)
            else:
                v_score_txt.set("…")
                score_label.configure(fg="#888888")
                _redraw_bar(0, "#888888")

        win.after(200, _poll)

    win.after(300, _poll)


def _draw_focus_overlay(disp, state: dict, dw: int, dh: int,
                        scale: float, frame) -> None:
    """
    Dibuja el overlay de Focus Assist sobre `disp` (array RGB display).
    Esquina superior derecha: número grande + barra + "max X".
    Rectángulo sutil que indica la ROI medida.
    No-op si focus_assist no está activado o no hay score todavía.
    """
    fa = state.get("focus_assist", {})
    if not fa.get("enabled"):
        return
    score = fa.get("score")
    if score is None:
        return

    max_s = fa.get("max_score") or score
    frac  = min(1.0, score / max(float(max_s), 1.0))

    # Color: verde > 80%, amarillo > 50%, rojo resto  (BGR para OpenCV)
    if frac > 0.80:
        col_bgr = (102, 221, 34)
    elif frac > 0.50:
        col_bgr = (0, 221, 255)
    else:
        col_bgr = (68, 68, 238)

    FONT  = cv2.FONT_HERSHEY_SIMPLEX
    score_txt = "%.0f" % score
    (tw, th), bl = cv2.getTextSize(score_txt, FONT, 1.10, 2)

    BOX_W = max(tw + 16, 118)
    BOX_H = th + 42           # número + barra + max label
    bx2 = dw - 8
    bx1 = bx2 - BOX_W
    by1 = 8
    by2 = by1 + BOX_H

    # Fondo semi-oscuro
    cv2.rectangle(disp, (bx1, by1), (bx2, by2), (10, 10, 10), -1)
    cv2.rectangle(disp, (bx1, by1), (bx2, by2), (60, 60, 60), 1)

    # Etiqueta "FOCUS"
    cv2.putText(disp, "FOCUS", (bx1 + 4, by1 + 11),
                FONT, 0.32, (160, 160, 160), 1)

    # Número grande (derecha del box)
    cv2.putText(disp, score_txt,
                (bx2 - tw - 6, by1 + th + 4),
                FONT, 1.10, col_bgr, 2)

    # Barra de progreso
    bar_x1 = bx1 + 4
    bar_x2 = bx2 - 4
    bar_y1 = by1 + th + 8
    bar_y2 = bar_y1 + 7
    cv2.rectangle(disp, (bar_x1, bar_y1), (bar_x2, bar_y2), (50, 50, 50), -1)
    fill_x = bar_x1 + int((bar_x2 - bar_x1) * frac)
    if fill_x > bar_x1:
        cv2.rectangle(disp, (bar_x1, bar_y1), (fill_x, bar_y2), col_bgr, -1)

    # "max N"
    cv2.putText(disp, "max %.0f" % max_s,
                (bx1 + 4, by2 - 3),
                FONT, 0.28, (130, 130, 130), 1)

    # Rectángulo que muestra la ROI medida (posición configurable)
    if frame is not None:
        H_f, W_f = frame.shape[:2]
        frac_roi = float(fa.get("roi_frac",    0.40))
        cx_frac  = float(fa.get("roi_cx_frac", 0.28))
        cy_frac  = float(fa.get("roi_cy_frac", 0.25))
        h2  = max(1, int(H_f * frac_roi / 2))
        w2  = max(1, int(W_f * frac_roi / 2))
        cx_i = max(w2, min(W_f - w2, int(W_f * cx_frac)))
        cy_i = max(h2, min(H_f - h2, int(H_f * cy_frac)))
        rx1 = int((cx_i - w2) * scale)
        ry1 = int((cy_i - h2) * scale)
        rx2 = int((cx_i + w2) * scale)
        ry2 = int((cy_i + h2) * scale)
        cv2.rectangle(disp, (rx1, ry1), (rx2, ry2), col_bgr, 1)
        cv2.putText(disp, "ROI foco", (rx1 + 4, ry1 + 12),
                    FONT, 0.30, col_bgr, 1)


# ---------------------------------------------------------------------------
# Fallback profile
# ---------------------------------------------------------------------------

class _FallbackProfile:
    def __init__(self, stage):
        driver = (stage.__class__.__name__.lower().replace("stage", "")
                  if stage else "none")
        self.stage_driver = driver
        self.axes = list(getattr(stage, "AXES", ["x", "y"])) if stage else []
        self.has_homing_dict = {
            ax: (stage.has_homing(ax) if stage else False) for ax in self.axes}
        self.range_mm = {}
        is_movi = "movi" in driver
        self.jog_step_default_mm = 1.0 if is_movi else 0.1
        self.jog_step_fine_mm    = 0.1 if is_movi else 0.01
        self.jog_step_coarse_mm  = 5.0 if is_movi else 0.5

    def has_axis(self, ax): return ax.lower() in self.axes
    def has_stage(self): return bool(self.axes)
    def has_z(self): return "z" in self.axes
    def homing_available(self, ax):
        return bool(self.has_homing_dict.get(ax.lower(), False))
    def can_reach(self, x, y): return True
    def range_label(self, ax): return ""
