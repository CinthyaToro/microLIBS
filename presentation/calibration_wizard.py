# -*- coding: utf-8 -*-
"""
presentation/calibration_wizard.py  (v4.1 — layout fix)
============================================================

Wizard de calibración espacial px → mm.

CAMBIOS v4.1:
- FIX LAYOUT: los botones "INICIAR / GUARDAR Y USAR" y "Cancelar" ahora
  quedan SIEMPRE visibles. Solución: se crean y packean con side="bottom"
  ANTES de crear el notebook y los controles, para que Tkinter les reserve
  espacio primero.
- Toda la lógica de calibración y la firma de open_calibration_wizard()
  son idénticas a v4.0 (sin cambios en funcionalidad).

DOS MÉTODOS:
  A. Regla: click en dos marcas conocidas (recomendado MoVi/webcam).
  B. Movimiento de stage: 3 puntos, absorbe distorsión de perspectiva
     (recomendado Thorlabs/Chameleon).
"""

from __future__ import annotations
import os
import math
import threading
import time
from typing import Callable, Optional

from service.calibration_service import StageCalibration


def _read_xy(stage, axes, default=(0.0, 0.0)):
    if stage is None:
        return list(default)
    try:
        x = stage.position("x") if "x" in axes else default[0]
        y = stage.position("y") if "y" in axes else default[1]
        return [float(x), float(y)]
    except Exception:
        return list(default)


def open_calibration_wizard(
    parent,
    vc,
    stage,
    session_dir: str,
    calib_dir: str,
    stage_driver: str = "",
    on_done: Optional[Callable[[StageCalibration], None]] = None,
    profile=None,
) -> None:
    import tkinter as tk
    from tkinter import messagebox, ttk
    from PIL import Image, ImageTk
    import cv2

    # ── Resolver perfil ──────────────────────────────────────────────────────
    if profile is None:
        try:
            from application.platform_profile import PlatformProfile
            profile = PlatformProfile.from_hardware(stage)
        except Exception:
            profile = _FallbackProfile(stage, stage_driver)

    driver    = profile.stage_driver or stage_driver or "default"
    axes      = profile.axes
    cam_label = vc.selected.label if vc.selected else ""

    # ── Calibración existente ────────────────────────────────────────────────
    existing = StageCalibration.load_persistent(calib_dir, driver, cam_label)
    if existing and existing.valid:
        dlg = tk.Toplevel(parent)
        dlg.title("Calibración guardada")
        dlg.geometry("460x290")
        dlg.resizable(False, False)
        dlg.grab_set()
        result = {"choice": None}

        tk.Label(dlg, text="Se encontró una calibración guardada para este hardware:",
                 font=("", 10, "bold")).pack(pady=(12, 4))
        tk.Label(dlg, text=existing.summary(), justify="left",
                 font=("Courier", 8), relief="sunken",
                 bg="#f5f5f5", pady=4, padx=8).pack(fill="x", padx=16, pady=4)
        tk.Label(dlg, text="Hardware: %s + %s" % (driver, cam_label or "cámara"),
                 fg="#555", font=("", 8)).pack()

        bf = tk.Frame(dlg); bf.pack(pady=10)

        def _use():    result["choice"] = "use";   dlg.destroy()
        def _recal():  result["choice"] = "recal"; dlg.destroy()
        def _cancel(): result["choice"] = "cancel"; dlg.destroy()

        tk.Button(bf, text="Usar esta calibración", width=22,
                  bg="#2e7d32", fg="white", command=_use).grid(
                      row=0, column=0, padx=6, pady=4)
        tk.Button(bf, text="Volver a calibrar", width=18,
                  command=_recal).grid(row=0, column=1, padx=6, pady=4)
        tk.Button(bf, text="Cancelar", width=12,
                  command=_cancel).grid(row=1, column=0, columnspan=2, pady=4)

        dlg.wait_window()
        ch = result["choice"]
        if ch == "use":
            if on_done: on_done(existing)
            return
        elif ch != "recal":
            return

    # ── Ventana principal ────────────────────────────────────────────────────
    win = tk.Toplevel(parent)
    win.title("Calibración espacial — %s" % driver.upper())

    # Tamaño adaptativo a la pantalla
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    win_w = max(820, min(1100, int(sw * 0.82)))
    win_h = max(540, min(750, int(sh * 0.84)))
    win.geometry("%dx%d" % (win_w, win_h))
    win.resizable(True, True)
    win.minsize(780, 520)

    S = {
        "alive": True, "last_frame": None, "clicks": [],
        "waiting": False, "method": None, "step": 0,
        "_scale": 1.0, "_offx": 0, "_offy": 0, "_last_click": None,
        "pt_a": None, "dist_mm": 20.0,
        "ruler_stage_xy": [0.0, 0.0],
        "origin_px": None, "after_x_px": None,
        "origin_mm": [0.0, 0.0],
        "dx_mm": profile.calib_move_dx_mm,
        "dy_mm": profile.calib_move_dy_mm,
    }

    cal = StageCalibration()
    cal.stage_driver = driver
    cal.camera_label = cam_label

    # ── Layout principal ─────────────────────────────────────────────────────
    main = tk.Frame(win)
    main.pack(fill="both", expand=True)

    img_canvas = tk.Canvas(main, bg="#111", cursor="crosshair", width=600)
    img_canvas.pack(side="left", fill="both", expand=True)

    right = tk.Frame(main, width=400, bd=1, relief="groove")
    right.pack(side="right", fill="y", padx=6, pady=6)
    right.pack_propagate(False)

    # ── BOTONES DE ACCIÓN — pack(side="bottom") PRIMERO ─────────────────────
    #
    # IMPORTANTE: estos widgets se crean y packean con side="bottom" ANTES
    # de cualquier otro widget en el panel derecho. Esto garantiza que Tkinter
    # les reserve espacio incluso cuando el resto del contenido desborda.
    #
    bf2 = tk.Frame(right)
    bf2.pack(side="bottom", fill="x", padx=6, pady=(4, 8))

    btn_action = tk.Button(bf2, text="INICIAR",
                           bg="#1565c0", fg="white",
                           font=("", 10, "bold"), width=16)
    btn_action.pack(side="left", padx=(0, 6))

    tk.Button(bf2, text="Cancelar", width=10,
              command=lambda: _close()).pack(side="left")

    ttk.Separator(right, orient="horizontal").pack(
        side="bottom", fill="x", padx=6, pady=(0, 4))

    # ── Instrucción activa (también en bottom para quedar sobre los botones) ─
    status_var = tk.StringVar(value="")
    tk.Label(right, textvariable=status_var, wraplength=370,
             justify="left", fg="#555", anchor="nw",
             font=("", 8)).pack(side="bottom", fill="x", padx=8, pady=(0, 2))

    instr_var = tk.StringVar(value="Elegí un método y presioná INICIAR.")
    instr_lbl = tk.Label(right, textvariable=instr_var, wraplength=370,
                         justify="left", anchor="nw", fg="#1b5e20",
                         relief="flat", font=("", 9, "bold"),
                         bg="#f1f8e9", pady=6, padx=8)
    instr_lbl.pack(side="bottom", fill="x", padx=6, pady=(0, 2))

    ttk.Separator(right, orient="horizontal").pack(
        side="bottom", fill="x", padx=6, pady=(4, 0))

    # ── Resto del contenido (top-down) ───────────────────────────────────────
    tk.Label(right, text="Calibración espacial",
             font=("", 11, "bold"), anchor="w").pack(
                 fill="x", padx=8, pady=(8, 2))

    hw_summary = "Stage: %s  |  Cámara: %s" % (driver.upper(), cam_label or "—")
    if profile.notes:
        hw_summary += "\n" + profile.notes
    tk.Label(right, text=hw_summary,
             font=("", 8), fg="#555", anchor="w", wraplength=370,
             justify="left", bg="#f9f9f9", padx=6, pady=4,
             relief="flat").pack(fill="x", padx=6, pady=(0, 4))

    nb = ttk.Notebook(right)
    nb.pack(fill="x", padx=6, pady=(0, 4))

    ruler_lbl = ("  ✓ Regla (recomendado)  "
                 if profile.calib_method == "ruler" else "  Regla  ")
    stage_lbl = ("  ✓ Movimiento stage (recomendado)  "
                 if profile.calib_method == "stage" else "  Movimiento stage  ")

    tab_r = tk.Frame(nb, pady=4)
    tab_s = tk.Frame(nb, pady=4)
    nb.add(tab_r, text=ruler_lbl)
    nb.add(tab_s, text=stage_lbl)

    if profile.calib_method == "stage" and stage is not None:
        nb.select(1)

    # ── TAB REGLA ────────────────────────────────────────────────────────────
    tk.Label(tab_r, justify="left", font=("", 9), fg="#333", text=(
        "1. Poné una regla o patrón milimetrado bajo la cámara.\n"
        "2. Verificá/actualizá la posición del stage abajo.\n"
        "3. Presioná INICIAR.\n"
        "4. Click en la marca de 0 mm de la regla.\n"
        "5. Click en la marca de N mm elegida.\n"
        "   Cuanto más separados los puntos, más precisión."
    )).pack(anchor="w", padx=8, pady=4)

    rf = tk.Frame(tab_r); rf.pack(fill="x", padx=8, pady=2)
    tk.Label(rf, text="Distancia entre clicks (mm):").pack(side="left")
    v_ruler_dist = tk.StringVar(value="20")
    tk.Entry(rf, textvariable=v_ruler_dist, width=7).pack(side="left", padx=4)

    rof = tk.LabelFrame(tab_r,
                        text="Posición actual del stage (mm)  ← ancla la calibración",
                        padx=6, pady=4)
    rof.pack(fill="x", padx=8, pady=6)

    _rxy = _read_xy(stage, axes)
    v_rox = tk.StringVar(value="%.4f" % _rxy[0])
    v_roy = tk.StringVar(value="%.4f" % _rxy[1])
    tk.Label(rof, text="X (mm):").grid(row=0, column=0, sticky="w")
    tk.Entry(rof, textvariable=v_rox, width=10).grid(row=0, column=1, padx=4)
    tk.Label(rof, text="Y (mm):").grid(row=1, column=0, sticky="w")
    tk.Entry(rof, textvariable=v_roy, width=10).grid(row=1, column=1, padx=4)
    tk.Label(rof,
             text="(leída del stage)" if stage else "Sin stage: ingresá manualmente",
             fg="#666", font=("", 8)).grid(row=2, column=0, columnspan=2, sticky="w")

    def _refresh_ruler_pos():
        xy = _read_xy(stage, axes)
        v_rox.set("%.4f" % xy[0])
        v_roy.set("%.4f" % xy[1])

    tk.Button(rof, text="↺ Leer posición actual", font=("", 8),
              command=_refresh_ruler_pos).grid(row=3, column=0, columnspan=2,
                                              sticky="w", pady=(4, 0))

    # ── TAB STAGE ────────────────────────────────────────────────────────────
    if stage is None:
        tk.Label(tab_s,
                 text="⚠  Sin stage conectado.\nUsá el método con regla.",
                 fg="#b71c1c", font=("", 9, "bold")).pack(padx=8, pady=12)
    else:
        tk.Label(tab_s, justify="left", font=("", 9), fg="#333", text=(
            "1. Presioná INICIAR.\n"
            "2. Click en un punto visible de la muestra (esquina, marca).\n"
            "3. El stage se mueve +%.3f mm en X.\n"
            "4. Click en el MISMO punto (ahora desplazado en la imagen).\n"
            "5. El stage se mueve +%.3f mm en Y.\n"
            "6. Click en el MISMO punto." % (
                profile.calib_move_dx_mm, profile.calib_move_dy_mm)
        )).pack(anchor="w", padx=8, pady=4)

        sf = tk.LabelFrame(tab_s, text="Distancias de movimiento (mm)",
                           padx=6, pady=4)
        sf.pack(fill="x", padx=8, pady=4)
        tk.Label(sf, text="En X:").grid(row=0, column=0, sticky="w")
        v_dx = tk.StringVar(value=str(profile.calib_move_dx_mm))
        tk.Entry(sf, textvariable=v_dx, width=8).grid(row=0, column=1, padx=4)
        tk.Label(sf, text="En Y:").grid(row=1, column=0, sticky="w")
        v_dy = tk.StringVar(value=str(profile.calib_move_dy_mm))
        tk.Entry(sf, textvariable=v_dy, width=8).grid(row=1, column=1, padx=4)
        tk.Label(sf, text="Ajustados para %s" % driver.upper(),
                 fg="#666", font=("", 8)).grid(row=2, column=0,
                                               columnspan=2, sticky="w")

        of = tk.LabelFrame(tab_s, text="Posición actual del stage (mm)",
                           padx=6, pady=4)
        of.pack(fill="x", padx=8, pady=2)
        _sxy = _read_xy(stage, axes)
        v_ox = tk.StringVar(value="%.4f" % _sxy[0])
        v_oy = tk.StringVar(value="%.4f" % _sxy[1])
        tk.Label(of, text="X:").grid(row=0, column=0, sticky="w")
        tk.Entry(of, textvariable=v_ox, width=10).grid(row=0, column=1, padx=4)
        tk.Label(of, text="Y:").grid(row=1, column=0, sticky="w")
        tk.Entry(of, textvariable=v_oy, width=10).grid(row=1, column=1, padx=4)

        def _refresh_stage_pos():
            xy = _read_xy(stage, axes)
            v_ox.set("%.4f" % xy[0])
            v_oy.set("%.4f" % xy[1])
            if profile.has_z():
                try: v_oz.set("%.4f" % stage.position("z"))
                except Exception: pass

        tk.Button(of, text="↺ Leer posición actual", font=("", 8),
                  command=_refresh_stage_pos).grid(row=2, column=0,
                                                   columnspan=2,
                                                   sticky="w", pady=(4, 0))

        home_axes = [ax for ax in ["x", "y"] if profile.homing_available(ax)]
        if home_axes:
            hf = tk.LabelFrame(tab_s, text="Homing", padx=6, pady=4)
            hf.pack(fill="x", padx=8, pady=2)
            for i, ax in enumerate(home_axes):
                def _do_home(a=ax):
                    threading.Thread(target=lambda: _home_axis(a),
                                     daemon=True).start()
                tk.Button(hf, text="Home %s" % ax.upper(), width=10,
                          command=_do_home).grid(row=0, column=i, padx=4)
            tk.Label(hf, text="Recomendado antes de calibrar",
                     fg="#666", font=("", 8)).grid(
                row=1, column=0, columnspan=len(home_axes), sticky="w")

        def _home_axis(axis):
            try:
                stage.home(axis)
                _refresh_stage_pos()
            except Exception as e:
                win.after(0,
                          lambda: _set_instr("Error homing %s: %s" % (axis, e),
                                             "#b71c1c"))

        if profile.has_z():
            zf = tk.LabelFrame(tab_s, text="Ajuste de foco — Eje Z",
                               padx=6, pady=4)
            zf.pack(fill="x", padx=8, pady=4)

            zrow = tk.Frame(zf); zrow.pack(fill="x")
            tk.Label(zrow, text="Z:").pack(side="left")
            try: _z0 = "%.4f" % stage.position("z")
            except Exception: _z0 = "—"
            v_oz = tk.StringVar(value=_z0)
            tk.Label(zrow, textvariable=v_oz, width=10, anchor="e",
                     relief="sunken", bg="#f0f0f0").pack(side="left", padx=2)
            tk.Label(zrow, text="mm").pack(side="left")

            zstep_row = tk.Frame(zf); zstep_row.pack(fill="x", pady=(4, 0))
            tk.Label(zstep_row, text="Paso Z (mm):").pack(side="left")
            v_zstep = tk.StringVar(value=str(profile.jog_step_fine_mm))
            tk.Entry(zstep_row, textvariable=v_zstep, width=7).pack(
                side="left", padx=4)

            zbtn = tk.Frame(zf); zbtn.pack(fill="x", pady=2)

            def _jog_z(sign):
                try:
                    step = float(v_zstep.get().replace(",", ".")) * sign
                    threading.Thread(target=lambda: _move_z(step),
                                     daemon=True).start()
                except ValueError:
                    pass

            def _move_z(delta):
                try:
                    stage.move_rel("z", delta)
                    time.sleep(0.1)
                    try: v_oz.set("%.4f" % stage.position("z"))
                    except Exception: pass
                except Exception as e:
                    win.after(0, lambda: status_var.set("Error Z: %s" % e))

            tk.Button(zbtn, text="Z ↑", width=7,
                      command=lambda: _jog_z(+1)).pack(side="left", padx=2)
            tk.Button(zbtn, text="Z ↓", width=7,
                      command=lambda: _jog_z(-1)).pack(side="left", padx=2)
            if profile.homing_available("z"):
                tk.Button(zbtn, text="Home Z", width=9,
                          command=lambda: threading.Thread(
                              target=lambda: _home_axis("z"),
                              daemon=True).start()).pack(side="left", padx=2)

            tk.Label(zf, text="Enfocar la muestra antes de calibrar X/Y",
                     fg="#666", font=("", 8)).pack(anchor="w")

    # ── Loop de imagen ────────────────────────────────────────────────────────
    _imref = [None]
    COLORS = [(0, 220, 0), (0, 140, 255), (220, 60, 0), (200, 0, 200)]
    NAMES  = ["A (0mm)", "B (dist)", "Origen", "+X", "+Y"]

    def _update_img():
        if not S["alive"] or not win.winfo_exists():
            return
        frame = None
        try:
            ps = getattr(vc, "_preview_state", None)
            if ps and ps.get("last_bgr") is not None:
                frame = ps["last_bgr"].copy()
        except Exception:
            pass

        if frame is not None:
            S["last_frame"] = frame
            H, W = frame.shape[:2]
            win.update_idletasks()
            cw = img_canvas.winfo_width()
            ch = img_canvas.winfo_height()
            if cw < 50 or ch < 50:
                win.after(80, _update_img)
                return

            scale = min(cw / W, ch / H)
            dw, dh = int(W * scale), int(H * scale)
            offx = (cw - dw) // 2
            offy = (ch - dh) // 2
            S.update({"_scale": scale, "_offx": offx, "_offy": offy})

            disp = cv2.cvtColor(
                cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_AREA),
                cv2.COLOR_BGR2RGB)

            for i, (cpx, cpy) in enumerate(S["clicks"]):
                xd, yd = int(cpx * scale), int(cpy * scale)
                c = COLORS[i % len(COLORS)]
                cv2.drawMarker(disp, (xd, yd), c, cv2.MARKER_CROSS, 26, 2)
                cv2.circle(disp, (xd, yd), 9, c, 1)
                lbl = NAMES[i] if i < len(NAMES) else str(i)
                cv2.putText(disp, lbl, (xd + 10, yd - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1)

            if S["waiting"]:
                cv2.rectangle(disp, (6, dh - 34), (dw - 6, dh - 8),
                              (0, 0, 0), -1)
                cv2.putText(disp, "CLICK para marcar el punto",
                            (12, dh - 14), cv2.FONT_HERSHEY_SIMPLEX,
                            0.65, (255, 255, 0), 2)

            full = Image.new("RGB", (cw, ch), (17, 17, 17))
            full.paste(Image.fromarray(disp), (offx, offy))
            imgtk = ImageTk.PhotoImage(full)
            _imref[0] = imgtk
            img_canvas.delete("all")
            img_canvas.create_image(0, 0, anchor="nw", image=imgtk)

        win.after(80, _update_img)

    def _canvas_click(ev):
        if not S["waiting"] or S["last_frame"] is None:
            return
        H, W = S["last_frame"].shape[:2]
        scale, offx, offy = S["_scale"], S["_offx"], S["_offy"]
        xd = max(0, min(ev.x - offx, int(W * scale) - 1))
        yd = max(0, min(ev.y - offy, int(H * scale) - 1))
        px = max(0, min(int(round(xd / scale)), W - 1))
        py = max(0, min(int(round(yd / scale)), H - 1))
        S["_last_click"] = (px, py)
        S["clicks"].append((px, py))
        S["waiting"] = False
        btn_action.configure(state="normal")
        status_var.set("Click en pixel (%d, %d). Presioná el botón para continuar."
                       % (px, py))

    img_canvas.bind("<Button-1>", _canvas_click)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _set_instr(msg, color="#1b5e20"):
        instr_var.set(msg)
        bg = {"#1b5e20": "#f1f8e9", "#0d47a1": "#e3f2fd"}.get(color, "#ffebee")
        instr_lbl.configure(fg=color, bg=bg)

    def _move_thread(x_mm, y_mm, cb=None):
        def _do():
            try:
                if stage is not None:
                    if "x" in axes: stage.move_abs("x", x_mm)
                    if "y" in axes: stage.move_abs("y", y_mm)
                time.sleep(0.5)
                if cb and win.winfo_exists():
                    win.after(0, cb)
            except Exception as e:
                if win.winfo_exists():
                    win.after(0, lambda: _set_instr("Error: %s" % e, "#b71c1c"))
        threading.Thread(target=_do, daemon=True).start()

    # ── MÉTODO A — REGLA ──────────────────────────────────────────────────────
    def _ruler_start():
        try:
            rx = float(v_rox.get().replace(",", "."))
            ry = float(v_roy.get().replace(",", "."))
        except ValueError:
            rx, ry = 0.0, 0.0
        S["ruler_stage_xy"] = [rx, ry]
        S.update({"method": "ruler", "step": 1,
                  "clicks": [], "_last_click": None, "waiting": True})
        btn_action.configure(state="disabled")
        _set_instr(
            "PASO 1 de 2\n\n"
            "Hacé click en la marca de 0 mm de la regla.\n\n"
            "Posición del stage registrada:\n"
            "  X = %.4f mm\n  Y = %.4f mm" % (rx, ry)
        )

    def _ruler_got_A():
        S["pt_a"] = S["_last_click"]
        try:
            S["dist_mm"] = float(v_ruler_dist.get().replace(",", "."))
        except ValueError:
            S["dist_mm"] = 20.0
        S.update({"step": 2, "_last_click": None, "waiting": True})
        btn_action.configure(state="disabled")
        _set_instr(
            "PASO 2 de 2\n\n"
            "Hacé click en la marca de %.1f mm de la regla.\n\n"
            "Cuanto más separados los puntos,\n"
            "más precisa la calibración." % S["dist_mm"]
        )

    def _ruler_got_B():
        px_a, py_a = S["pt_a"]
        px_b, py_b = S["_last_click"]
        dist_mm    = S["dist_mm"]
        dist_px    = math.sqrt((px_b - px_a)**2 + (py_b - py_a)**2)

        if dist_px < 5:
            _set_instr("Los puntos están muy juntos. Intentá de nuevo.",
                       "#b71c1c")
            S["clicks"] = []
            _ruler_start()
            return

        s   = dist_mm / dist_px
        ang = math.atan2(py_b - py_a, px_b - px_a)
        ca, sa = math.cos(ang), math.sin(ang)
        a  =  s * ca;  b_ =  s * sa
        c  = -s * sa;  d  =  s * ca

        rx, ry = S["ruler_stage_xy"]
        cal.A = [[a, b_], [c, d]]
        cal.t = [rx - (a * px_a + b_ * py_a),
                 ry - (c * px_a + d  * py_a)]
        cal.valid       = True
        cal.n_points    = 2
        cal.residual_mm = 0.0
        cal.fitted_iso  = time.strftime("%Y-%m-%dT%H:%M:%S")
        cal.notes = (
            "Ruler v4 | dist=%.2fmm | %.1fpx | ang=%.1fdeg | "
            "scale=%.5fmm/px | origin=(%.4f,%.4f)mm"
            % (dist_mm, dist_px, math.degrees(ang), s, rx, ry)
        )
        xb, yb = cal._transform(px_b, py_b)
        status_var.set(
            "Verificación: B = (%.4f, %.4f) mm  |  "
            "escala = %.5f mm/px  |  rot = %.2f°"
            % (xb, yb, s, math.degrees(ang))
        )
        _done()

    # ── MÉTODO B — STAGE ─────────────────────────────────────────────────────
    def _stage_start():
        if stage is None:
            messagebox.showwarning("Sin stage",
                                   "No hay stage conectado.\nUsá el método con regla.",
                                   parent=win)
            return
        try:
            S["origin_mm"] = [float(v_ox.get().replace(",", ".")),
                              float(v_oy.get().replace(",", "."))]
            S["dx_mm"] = float(v_dx.get().replace(",", "."))
            S["dy_mm"] = float(v_dy.get().replace(",", "."))
        except Exception:
            pass
        S.update({"method": "stage", "step": 1,
                  "clicks": [], "_last_click": None, "waiting": True})
        btn_action.configure(state="disabled")
        ox, oy = S["origin_mm"]
        _set_instr(
            "PASO 1 de 3\n\n"
            "Hacé click en un punto bien visible de la muestra\n"
            "(esquina, borde, marca precisa).\n\n"
            "Posición del stage: X=%.4f  Y=%.4f mm" % (ox, oy),
            "#0d47a1"
        )

    def _stage_got_origin():
        S["origin_px"] = S["_last_click"]
        ox, oy = S["origin_mm"]
        dx = S["dx_mm"]
        def after():
            S.update({"step": 2, "_last_click": None, "waiting": True})
            btn_action.configure(state="disabled")
            _set_instr(
                "PASO 2 de 3\n\n"
                "Stage movido +%.3f mm en X.\n"
                "La imagen se desplazó.\n\n"
                "Hacé click en el MISMO punto." % dx,
                "#0d47a1"
            )
        status_var.set("Moviendo +%.3f mm en X..." % dx)
        _move_thread(ox + dx, oy, cb=after)

    def _stage_got_after_x():
        S["after_x_px"] = S["_last_click"]
        ox, oy = S["origin_mm"]
        dy = S["dy_mm"]
        def go_y():
            def after():
                S.update({"step": 3, "_last_click": None, "waiting": True})
                btn_action.configure(state="disabled")
                _set_instr(
                    "PASO 3 de 3\n\n"
                    "Stage movido +%.3f mm en Y.\n\n"
                    "Hacé click en el MISMO punto." % dy,
                    "#0d47a1"
                )
            _move_thread(ox, oy + dy, cb=after)
        status_var.set("Volviendo al origen y moviendo +%.3f mm en Y..." % dy)
        _move_thread(ox, oy, cb=go_y)

    def _stage_got_after_y():
        ox, oy   = S["origin_mm"]
        dx, dy   = S["dx_mm"], S["dy_mm"]
        px0, py0 = S["origin_px"]
        px1, py1 = S["after_x_px"]
        px2, py2 = S["_last_click"]
        _move_thread(ox, oy)

        cal.clear_points()
        cal.add_point(px0, py0, ox,      oy,      label="origen")
        cal.add_point(px1, py1, ox + dx, oy,      label="+X")
        cal.add_point(px2, py2, ox,      oy + dy, label="+Y")

        ok = cal.fit()
        if not ok:
            _set_instr(
                "No se pudo calcular:\n%s\n\nIntentá con puntos más separados."
                % cal.notes, "#b71c1c")
            return

        # ── Verificar si la calibración parece sospechosa ─────────────────
        suspicious, reason = cal.looks_suspicious()
        if suspicious:
            _set_instr(
                "⚠  CALIBRACIÓN SOSPECHOSA\n\n"
                + reason + "\n\n"
                + cal.summary() + "\n\n"
                "POSIBLES CAUSAS:\n"
                "• Marcaste un punto incorrecto (ej.: intersección de grilla vecina)\n"
                "• Los 3 puntos están casi en línea recta\n"
                "• El stage se movió mientras marcabas un punto\n\n"
                "Podés GUARDAR igual o repetir la calibración.",
                "#b71c1c")
        else:
            _done()

    # ── Fin ───────────────────────────────────────────────────────────────────
    def _done():
        _set_instr("CALIBRACIÓN COMPLETA\n\n" + cal.summary())
        btn_action.configure(text="GUARDAR Y USAR", state="normal",
                             bg="#2e7d32", command=_save)

    def _save():
        try:
            os.makedirs(calib_dir, exist_ok=True)
            cal.save_session(session_dir)
            cal.save_persistent(calib_dir, stage_driver=driver,
                                camera_label=cam_label)
            S["alive"] = False
            if on_done: on_done(cal)
            win.destroy()
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=win)

    def _close():
        S["alive"] = False
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", _close)

    def _on_action():
        m, step = S["method"], S["step"]
        if m is None:
            tab = nb.index(nb.select())
            (_ruler_start if tab == 0 else _stage_start)()
            return
        if m == "ruler":
            {1: _ruler_got_A, 2: _ruler_got_B}.get(step, lambda: None)()
        elif m == "stage":
            {1: _stage_got_origin, 2: _stage_got_after_x,
             3: _stage_got_after_y}.get(step, lambda: None)()

    btn_action.configure(command=_on_action)
    win.after(200, _update_img)


# ── Fallback profile ──────────────────────────────────────────────────────────

class _FallbackProfile:
    def __init__(self, stage, driver):
        self.stage_driver = driver or (
            stage.__class__.__name__.lower().replace("stage", "")
            if stage else "none")
        self.axes = list(getattr(stage, "AXES", ["x", "y"])) if stage else []
        self.has_homing = {
            ax: (stage.has_homing(ax) if stage else False)
            for ax in self.axes}
        self.range_mm = {}
        self.calib_method      = "ruler" if "movi" in self.stage_driver else "stage"
        self.calib_move_dx_mm  = 10.0 if "movi" in self.stage_driver else 1.0
        self.calib_move_dy_mm  = 10.0 if "movi" in self.stage_driver else 1.0
        self.jog_step_default_mm = 1.0 if "movi" in self.stage_driver else 0.1
        self.jog_step_fine_mm    = 0.1 if "movi" in self.stage_driver else 0.01
        self.jog_step_coarse_mm  = 5.0 if "movi" in self.stage_driver else 0.5
        self.notes = ""

    def has_axis(self, ax):   return ax.lower() in self.axes
    def has_z(self):          return "z" in self.axes
    def homing_available(self, ax):
        return bool(self.has_homing.get(ax.lower(), False))
    def summary(self):
        return "Stage: %s | Ejes: %s" % (
            self.stage_driver, ", ".join(a.upper() for a in self.axes))
