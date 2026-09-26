# -*- coding: utf-8 -*-
"""
presentation/main_window.py  v3
================================
Wizard de inicio de sesión + panel de control microLIBS.

Cambios respecto a v2:
• Wizard: sección láser (driver / host / puerto / conexión)
• Panel: banner de hardware (Stage | Cámara | Láser)
• Panel: LabelFrame Láser con ARM/DISARM/FIRE/leer-estado/set-parámetros
• Scan plan: botón "Plan sesión anterior..." copia scan_plan.json a sesión actual
• Scan: pasa laser e invert_y_axis al ScanRunner
• Y-inversion: checkbox en wizard (default True para Thorlabs)
"""
from __future__ import annotations
import json, os, time, threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from application.session_manager import sanitize_name
from hal.factory import create_stage, scan_movi_port, list_serial_ports
from presentation.camera_selector import select_camera_gui
from presentation.preview_panel import open_preview
from presentation.spectrum_viewer import SpectrumViewer
from service.shutdown_service import ShutdownSequence
from service.vision_service import VisionService


# ─── Wizard de inicio de sesión ──────────────────────────────────────────────

def show_session_wizard(root, initial: dict, svc: VisionService) -> dict:
    result = {"ok": False}
    win = tk.Toplevel(root)
    win.title("microLIBS — Preparar sesión")

    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry("%dx%d" % (max(720, min(860, int(sw * 0.65))),
                             max(580, min(720, int(sh * 0.87)))))
    win.resizable(True, True)
    win.minsize(680, 540)

    default_base = os.path.join(os.path.expanduser("~"), "microLIBS_captures")

    # ── Variables ─────────────────────────────────────────────────────────────
    v_sample   = tk.StringVar(value=initial.get("sample_name", "muestra_01"))
    v_operator = tk.StringVar(value=initial.get("operator", ""))
    v_base     = tk.StringVar(value=initial.get("base_dir", default_base))
    v_fps      = tk.StringVar(value=str(initial.get("preview_fps", 8.0)))
    v_camera   = tk.StringVar(value="(no seleccionada)")
    camera_desc = {"desc": None, "stage": None}

    v_stage    = tk.StringVar(value=initial.get("stage_driver", "thorlabs_sim"))
    v_stport   = tk.StringVar(value=initial.get("stage_port", "COM4"))
    v_inv_y    = tk.IntVar(value=int(initial.get("stage_invert_y", 1)))
    v_trigger  = tk.StringVar(value=initial.get("trigger_mode", "soft_delay"))

    v_laser_driver = tk.StringVar(value=initial.get("laser_driver", "none"))
    v_laser_host   = tk.StringVar(value=initial.get("laser_host", "127.0.0.1"))
    v_laser_port   = tk.StringVar(value=str(initial.get("laser_port", 27182)))
    v_laser_conn   = tk.StringVar(value=initial.get("laser_conn_type", "usb"))

    v_use_ard = tk.IntVar(value=int(initial.get("use_arduino", 0)))
    v_ard_port = tk.StringVar(value=initial.get("arduino_port", "COM3"))
    v_ard_baud = tk.StringVar(value=str(initial.get("arduino_baud", 115200)))

    v_detect_status = tk.StringVar(value="")
    detecting = {"flag": False}

    # ── Callbacks ─────────────────────────────────────────────────────────────
    def pick_base():
        d = filedialog.askdirectory(title="Carpeta base",
                                    initialdir=v_base.get() or os.getcwd())
        if d:
            v_base.set(d)

    def pick_camera():
        try:
            cameras = select_camera_gui(svc, parent_tk=win)
            desc_m = cameras["muestra"]
            camera_desc["desc"]  = desc_m
            camera_desc["stage"] = cameras.get("stage")
            v_camera.set(desc_m.label)
            fps_row.grid() if desc_m.kind == "chameleon" else fps_row.grid_remove()
        except Exception as e:
            messagebox.showerror("Error cámara", str(e), parent=win)

    def _update_stage_widgets(*_):
        drv = v_stage.get().lower()
        if drv in ("thorlabs", "thorlabs_sim"):
            v_inv_y.set(1); cb_invy.configure(state="normal")
        elif drv == "movi":
            v_inv_y.set(0); cb_invy.configure(state="normal")
        else:
            v_inv_y.set(0); cb_invy.configure(state="disabled")

    def _update_laser_widgets(*_):
        if v_laser_driver.get() == "ekspla":
            laser_srv_row.grid()
        else:
            laser_srv_row.grid_remove()

    def _do_detect_movi():
        detecting["flag"] = True
        win.after(0, lambda: btn_detect.configure(state="disabled", text="Detectando…"))
        win.after(0, lambda: v_detect_status.set("Escaneando puertos…"))
        port = scan_movi_port(timeout_per_port=2.5,
                              log_fn=lambda m: win.after(0, lambda _m=m: v_detect_status.set(_m)))
        def _finish():
            detecting["flag"] = False
            btn_detect.configure(state="normal", text="Detectar")
            if port:
                v_stport.set(port)
                v_detect_status.set("✅ MoVi en %s" % port)
            else:
                v_detect_status.set("❌ MoVi no encontrado")
                avail = list_serial_ports()
                if avail:
                    messagebox.showwarning("MoVi no encontrado",
                        "No se detectó respuesta del MoVi.\n\n"
                        "Puertos disponibles:\n%s" % "\n".join("  • " + p for p in avail),
                        parent=win)
        win.after(0, _finish)

    def detect_movi():
        if detecting["flag"]:
            return
        if v_stage.get().lower() != "movi":
            messagebox.showinfo("Detección MoVi",
                "La detección automática es solo para el stage 'movi'.", parent=win)
            return
        threading.Thread(target=_do_detect_movi, daemon=True).start()

    def show_ports_menu(ev=None):
        ports = list_serial_ports()
        if not ports:
            messagebox.showinfo("Puertos", "No se encontraron puertos serie.", parent=win)
            return
        m = tk.Menu(win, tearoff=0)
        for p in ports:
            dev = p.split()[0]
            m.add_command(label=p, command=lambda d=dev: v_stport.set(d))
        try:
            m.tk_popup(ev.x_root, ev.y_root)
        finally:
            m.grab_release()

    def start():
        if not v_base.get().strip():
            messagebox.showerror("Error", "Elegí una carpeta base.", parent=win); return
        if camera_desc["desc"] is None:
            messagebox.showerror("Error", "Seleccioná una cámara.", parent=win); return
        fps = 15.0
        if camera_desc["desc"].kind == "chameleon":
            try:
                fps = float(v_fps.get())
                if fps <= 0: raise ValueError()
            except Exception:
                messagebox.showerror("Error", "FPS inválido.", parent=win); return
        try: baud = int(str(v_ard_baud.get()).strip())
        except Exception: baud = 115200
        try: laser_port = int(v_laser_port.get().strip())
        except Exception: laser_port = 27182

        result.update({
            "ok": True,
            "stage_cam_desc":  camera_desc.get("stage"),
            "sample_name":     v_sample.get().strip(),
            "operator":        v_operator.get().strip(),
            "base_dir":        v_base.get().strip(),
            "preview_fps":     fps,
            "use_arduino":     bool(v_use_ard.get() == 1),
            "arduino_port":    v_ard_port.get().strip(),
            "arduino_baud":    baud,
            "stage_driver":    v_stage.get().strip().lower(),
            "stage_port":      v_stport.get().strip(),
            "stage_invert_y":  bool(v_inv_y.get() == 1),
            "trigger_mode":    v_trigger.get().strip().lower(),
            "laser_driver":    v_laser_driver.get().strip().lower(),
            "laser_host":      v_laser_host.get().strip(),
            "laser_port":      laser_port,
            "laser_conn_type": v_laser_conn.get().strip().lower(),
        })
        win.destroy()

    def cancel():
        result["ok"] = False; win.destroy()

    # ── Layout scroll ─────────────────────────────────────────────────────────
    canv = tk.Canvas(win, borderwidth=0, highlightthickness=0)
    vsb  = tk.Scrollbar(win, orient="vertical", command=canv.yview)
    canv.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canv.pack(side="left", fill="both", expand=True)
    frm = tk.Frame(canv)
    fwid = canv.create_window((0, 0), window=frm, anchor="nw")
    frm.bind("<Configure>", lambda e: canv.configure(scrollregion=canv.bbox("all")))
    canv.bind("<Configure>", lambda e: canv.itemconfig(fwid, width=e.width))
    for ev, d in (("<MouseWheel>", lambda e: int(-1*(e.delta/120))),
                  ("<Button-4>", lambda e: -1), ("<Button-5>", lambda e: 1)):
        canv.bind_all(ev, lambda e, _d=d: canv.yview_scroll(_d(e), "units"))
    frm.columnconfigure(1, weight=1)

    def row(label, widget, r, colspan=1):
        tk.Label(frm, text=label, anchor="w", width=22).grid(
            row=r, column=0, sticky="w", pady=5, padx=(10, 4))
        widget.grid(row=r, column=1, sticky="ew", pady=5, padx=(0, 10), columnspan=colspan)

    # ── Muestra / Operador / Base / Cámara ────────────────────────────────────
    row("Muestra:",  tk.Entry(frm, textvariable=v_sample), 0)
    row("Operador:", tk.Entry(frm, textvariable=v_operator), 1)

    base_f = tk.Frame(frm)
    tk.Entry(base_f, textvariable=v_base).pack(side="left", fill="x", expand=True)
    tk.Button(base_f, text="Elegir…", command=pick_base, width=9).pack(side="left", padx=6)
    row("Carpeta base:", base_f, 2)

    cam_f = tk.Frame(frm)
    tk.Label(cam_f, textvariable=v_camera, anchor="w").pack(side="left", fill="x", expand=True)
    tk.Button(cam_f, text="Cámara…", command=pick_camera, width=9).pack(side="left", padx=6)
    row("Cámara:", cam_f, 3)

    fps_row = tk.Frame(frm)
    tk.Label(fps_row, text="Preview FPS:", anchor="w", width=22).pack(side="left")
    tk.Entry(fps_row, textvariable=v_fps, width=8).pack(side="left")
    fps_row.grid(row=4, column=0, columnspan=2, sticky="w", pady=3, padx=10)
    fps_row.grid_remove()

    # ── Stage ─────────────────────────────────────────────────────────────────
    stage_f = tk.Frame(frm)
    tk.OptionMenu(stage_f, v_stage, "movi", "thorlabs", "thorlabs_sim", "sim",
                  command=_update_stage_widgets).pack(side="left")
    tk.Label(stage_f, text="  Puerto:").pack(side="left", padx=(12, 2))
    ep = tk.Entry(stage_f, textvariable=v_stport, width=8)
    ep.pack(side="left")
    ep.bind("<Button-3>", show_ports_menu)
    btn_detect = tk.Button(stage_f, text="Detectar", width=9, command=detect_movi,
                           bg="#1565c0", fg="white")
    btn_detect.pack(side="left", padx=(6, 0))
    tk.Label(stage_f, textvariable=v_detect_status, fg="#1a6a1a",
             anchor="w").pack(side="left", padx=(6, 0))
    row("Stage:", stage_f, 5)

    inv_f = tk.Frame(frm)
    cb_invy = tk.Checkbutton(inv_f,
        text="⚠ Invertir eje Y stage  (activo por defecto en Thorlabs)",
        variable=v_inv_y)
    cb_invy.pack(side="left", padx=4)
    inv_f.grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 2), padx=10)

    note_f = tk.Frame(frm)
    tk.Label(note_f,
             text='💡 "Detectar": escanea USB buscando MoVi. '
                  'Click derecho en "Puerto" para ver lista.',
             fg="#555", font=("", 8), anchor="w").pack(side="left", padx=4)
    note_f.grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 2), padx=10)

    # ── Trigger ───────────────────────────────────────────────────────────────
    trig_f = tk.Frame(frm)
    tk.OptionMenu(trig_f, v_trigger, "soft_delay", "ttl_arduino", "none").pack(side="left")
    row("Trigger:", trig_f, 8)

    # ── Separador ─────────────────────────────────────────────────────────────
    tk.Frame(frm, height=1, bg="#bbbbbb").grid(row=9, column=0, columnspan=2,
                                                sticky="ew", padx=10, pady=(4, 0))
    tk.Label(frm, text="── Láser ──────────────────────────────",
             fg="#555", font=("", 8)).grid(row=10, column=0, columnspan=2,
                                            sticky="w", padx=10, pady=(0, 2))

    laser_drv_f = tk.Frame(frm)
    tk.Label(laser_drv_f, text="Driver:").pack(side="left")
    tk.OptionMenu(laser_drv_f, v_laser_driver,
                  "none", "ekspla", "sim_laser",
                  command=_update_laser_widgets).pack(side="left", padx=(4, 14))
    tk.Label(laser_drv_f, text="Conexión HW:").pack(side="left")
    tk.OptionMenu(laser_drv_f, v_laser_conn, "usb", "com3", "lan").pack(side="left", padx=4)
    row("Láser:", laser_drv_f, 11)

    laser_srv_row = tk.Frame(frm)
    tk.Label(laser_srv_row, text="laser_server.py → Host:").pack(side="left")
    tk.Entry(laser_srv_row, textvariable=v_laser_host, width=14).pack(side="left", padx=2)
    tk.Label(laser_srv_row, text="Puerto:").pack(side="left", padx=(6, 2))
    tk.Entry(laser_srv_row, textvariable=v_laser_port, width=7).pack(side="left", padx=2)
    laser_srv_row.grid(row=12, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 2))
    laser_srv_row.grid_remove()

    tk.Label(frm,
             text="⚠ Para 'ekspla': antes de iniciar ejecutá  python32 laser_server.py  "
                  "en el PC con las DLLs de REMOTECONTROL.",
             fg="#8a4a00", font=("", 7), anchor="w", wraplength=620).grid(
             row=13, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 4))

    # ── Arduino ───────────────────────────────────────────────────────────────
    tk.Frame(frm, height=1, bg="#bbbbbb").grid(row=14, column=0, columnspan=2,
                                                sticky="ew", padx=10, pady=(4, 0))
    ard_f = tk.Frame(frm)
    tk.Checkbutton(ard_f, text="Usar Arduino", variable=v_use_ard).pack(side="left")
    tk.Label(ard_f, text="Port:").pack(side="left", padx=(10, 2))
    tk.Entry(ard_f, textvariable=v_ard_port, width=10).pack(side="left")
    tk.Label(ard_f, text="Baud:").pack(side="left", padx=(10, 2))
    tk.Entry(ard_f, textvariable=v_ard_baud, width=10).pack(side="left")
    row("Arduino:", ard_f, 15)

    # ── Botones ───────────────────────────────────────────────────────────────
    btns = tk.Frame(frm)
    btns.grid(row=17, column=0, columnspan=2, pady=16, sticky="e", padx=10)
    tk.Button(btns, text="Cancelar", width=12, command=cancel).pack(side="right", padx=6)
    tk.Button(btns, text="▶ Iniciar sesión", width=14, command=start,
              bg="#2e7d32", fg="white").pack(side="right", padx=6)

    _update_stage_widgets()
    _update_laser_widgets()

    win.grab_set()
    root.wait_window(win)
    return result


# ─── Panel de control ─────────────────────────────────────────────────────────

def open_control_panel(root, svc: VisionService, session_mgr,
                       stage, arduino, params: dict,
                       laser=None, spectrometer=None, exp_cfg=None,
                       stage_cam_desc=None, calibration=None) -> None:
    from service.scan_service import ScanRunner

    sample       = session_mgr.sample_name
    operator     = session_mgr.operator
    images_dir   = session_mgr.images_dir
    events_dir   = session_mgr.events_dir
    session_dir  = session_mgr.session_dir
    preview_fps  = float(params.get("preview_fps", 8.0))
    stage_driver = params.get("stage_driver", "")
    invert_y     = bool(params.get("stage_invert_y", False))

    ctrl = tk.Toplevel(root)
    ctrl.title("microLIBS — Control")
    sw, sh = ctrl.winfo_screenwidth(), ctrl.winfo_screenheight()
    ctrl.geometry("%dx%d" % (max(680, min(900, int(sw * 0.64))),
                              max(660, min(920, int(sh * 0.92)))))
    ctrl.resizable(True, True)
    ctrl.minsize(660, 620)

    # ── Spectrum Viewer ──────────────────────────────────────────────────────
    spectrum_viewer = SpectrumViewer(ctrl)

    # Canvas scrollable
    canvas = tk.Canvas(ctrl, borderwidth=0)
    vsb    = tk.Scrollbar(ctrl, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    frm = tk.Frame(canvas)
    fw  = canvas.create_window((0, 0), window=frm, anchor="nw")
    frm.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(fw, width=e.width))
    for ev, d in (("<MouseWheel>", lambda e: int(-1*(e.delta/120))),
                  ("<Button-4>", lambda e: -1), ("<Button-5>", lambda e: 1)):
        canvas.bind_all(ev, lambda e, _d=d: canvas.yview_scroll(_d(e), "units"))
    frm.columnconfigure(0, weight=1)

    # ── Banner de hardware ────────────────────────────────────────────────────
    def _hw_text():
        parts = []
        if stage is not None:
            parts.append("Stage: %s" % stage.__class__.__name__)
        elif stage_driver:
            parts.append("Stage: %s (no conectado)" % stage_driver)
        else:
            parts.append("Stage: ninguno")
        parts.append("Cámara: %s" % (svc.selected.label if svc.selected else "ninguna"))
        if laser is not None:
            n = laser.__class__.__name__
            if hasattr(laser, "_params") and laser._params.get("host"):
                n += " [%s:%s]" % (laser._params["host"], laser._params.get("port",""))
            parts.append("Láser: %s" % n)
        else:
            parts.append("Láser: ninguno")
        spec_drv = (params.get("spectrometer_driver") or "ninguno").lower()
        if spectrometer and spectrometer.is_connected:
            parts.append("Espectrómetro: %s OK" % spec_drv)
        elif spectrometer is not None:
            parts.append("Espectrómetro: %s (error conexión)" % spec_drv)
        else:
            parts.append("Espectrómetro: ninguno")
        if invert_y:
            parts.append("⚠ Y invertido")
        return "  │  ".join(parts)

    hw_lbl = tk.Label(frm, text=_hw_text(),
                      bg="#e8f5e9", fg="#1b5e20", anchor="w",
                      font=("", 9, "bold"), padx=8, pady=4, relief="groove")
    hw_lbl.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))

    # ── Status + log ──────────────────────────────────────────────────────────
    status = tk.StringVar(value="Listo.")
    tk.Label(frm, textvariable=status, anchor="w").grid(
        row=1, column=0, sticky="ew", padx=10, pady=(4, 0))

    log_wrap = tk.Frame(frm)
    log_wrap.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
    log_wrap.columnconfigure(0, weight=1)
    log_txt = tk.Text(log_wrap, height=5, wrap="word", state="disabled")
    log_txt.grid(row=0, column=0, sticky="ew")
    log_scr = tk.Scrollbar(log_wrap, command=log_txt.yview)
    log_scr.grid(row=0, column=1, sticky="ns")
    log_txt.configure(yscrollcommand=log_scr.set)

    def ui_log(msg: str):
        line = "[%s] %s\n" % (time.strftime("%H:%M:%S"), msg)
        try:
            log_txt.configure(state="normal")
            log_txt.insert("end", line)
            log_txt.see("end")
            log_txt.configure(state="disabled")
        except Exception:
            pass

    runner_ref    = {"runner": None}

    # La secuencia de apagado vive en service/shutdown_service.py: es
    # orquestacion, no interfaz. Aca solo queda cerrar la ventana.
    # El orden fijo Ocean -> EKSPLA -> Thorlabs -> Chameleon lo verifica
    # tests/test_shutdown_sequence.py.
    _shutdown_seq = ShutdownSequence(log=ui_log)

    def safe_shutdown():
        reporte = _shutdown_seq.run(
            runner       = runner_ref.get("runner"),
            spectrometer = spectrometer,
            laser        = laser,
            stage        = stage,
            vision       = svc,
            arduino      = arduino,
        )
        if reporte["ya_estaba"]:
            return

        try: root.quit()
        except Exception: pass
        try: root.destroy()
        except Exception: pass

    ctrl.bind("<Escape>", lambda _e: safe_shutdown())
    ctrl.protocol("WM_DELETE_WINDOW", safe_shutdown)

    # ── Evento manual ─────────────────────────────────────────────────────────
    ev_frm = tk.LabelFrame(frm, text="Evento manual (captura + Arduino)",
                            padx=8, pady=4)
    ev_frm.grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 4))
    ev_frm.columnconfigure(0, weight=1)

    v_p = tk.StringVar(value="200")
    v_d = tk.StringVar(value="0")
    v_a = tk.StringVar(value="0")
    v_s = tk.StringVar(value="1")
    v_settle = tk.StringVar(value="0.05")

    pf2 = tk.Frame(ev_frm); pf2.pack(fill="x")
    for lbl, var in [("P (us):", v_p), ("D (us):", v_d), ("A (ms):", v_a), ("S:", v_s)]:
        tk.Label(pf2, text=lbl).pack(side="left")
        tk.Entry(pf2, textvariable=var, width=7).pack(side="left", padx=(2, 8))
    sf2 = tk.Frame(ev_frm); sf2.pack(fill="x", pady=2)
    tk.Label(sf2, text="Settle (s):").pack(side="left")
    tk.Entry(sf2, textvariable=v_settle, width=8).pack(side="left", padx=(2, 8))

    def _num(v, cast=float, default=0):
        try: return cast(str(v).strip())
        except Exception: return default

    def do_capture(kind):
        out = svc.request_capture(save_dir=images_dir,
                                  base_name=sanitize_name(sample), kind=kind,
                                  extra_meta={"sample_name": sample, "operator": operator,
                                              "session_dir": session_dir})
        msg = "Captura %s → %s" % (kind, os.path.basename(out["image_path"]))
        status.set("✅ " + msg); ui_log(msg); return out

    def do_light(on):
        if arduino is None: status.set("⚠️ Sin Arduino."); return
        r = arduino.light(on)
        msg = ("💡 ON" if on else "💡 OFF") + " | " + (r["lines"][-1] if r.get("lines") else "")
        status.set(msg); ui_log(msg)

    ev_counter = {"n": 0}
    def event_microLIBS():
        ev_counter["n"] += 1
        n = ev_counter["n"]; ts = time.strftime("%Y%m%d_%H%M%S")
        settle_s = _num(v_settle.get(), float, 0.05)
        p_us = _num(v_p.get(), int, 200); d_us = _num(v_d.get(), int, 0)
        a_ms = _num(v_a.get(), int, 0);   s_t  = _num(v_s.get(), int, 1)
        log = {"event_n": n, "timestamp": ts,
               "params": {"P_us": p_us, "D_us": d_us, "A_ms": a_ms, "S": s_t},
               "pre": None, "m14": None, "post": None, "error": None}
        ui_log("▶ Evento %d: P=%d D=%d A=%d S=%d" % (n, p_us, d_us, a_ms, s_t))
        try:
            if arduino: log["light_on"] = arduino.light(True)
            time.sleep(max(0.0, settle_s)); status.set("PRE…")
            log["pre"] = do_capture("pre"); status.set("M14…")
            log["m14"] = arduino.fire(p_us, d_us, a_ms, s_t) if arduino else {"cmd": "M14 (sin arduino)"}
            time.sleep(max(0.0, settle_s)); status.set("POST…")
            log["post"] = do_capture("post"); status.set("✅ Evento %d OK" % n)
        except Exception as e:
            log["error"] = repr(e); status.set("❌ %s" % repr(e)); ui_log("❌ " + repr(e))
        finally:
            if arduino:
                try: arduino.light(False)
                except Exception: pass
            try:
                from application.session_manager import safe_write_json
                suffix = "_ERROR" if log.get("error") else ""
                safe_write_json(os.path.join(events_dir,
                    "event_%04d_%s%s.json" % (n, ts, suffix)), log)
            except Exception: pass

    btns_ev = tk.Frame(ev_frm); btns_ev.pack(fill="x", pady=2)
    for lbl, cmd, kw in [
        ("Captura PRE",  lambda: do_capture("pre"),  {}),
        ("Captura POST", lambda: do_capture("post"), {}),
        ("💡 ON",  lambda: do_light(True),  {}),
        ("💡 OFF", lambda: do_light(False), {}),
        ("▶ PRE→M14→POST", event_microLIBS, {"bg": "#1565c0", "fg": "white"}),
    ]:
        tk.Button(btns_ev, text=lbl, command=cmd, **kw).pack(side="left", padx=3)

    # ── Estado compartido: dark capturado (para el scan) ──────────────────────
    active_dark = [None]    # [dict channels | None] — fondo activo en sesión

    # ── Panel Láser ───────────────────────────────────────────────────────────
    _build_laser_panel(frm, grid_row=4, laser=laser,
                       ui_log=ui_log, status_var=status, ctrl_win=ctrl,
                       spectrometer=spectrometer, session_dir=session_dir,
                       spectrum_viewer=spectrum_viewer, active_dark=active_dark)

    # ── Scan plan ─────────────────────────────────────────────────────────────
    scan_lf = tk.LabelFrame(frm, text="Scan plan (ScanRunner)", padx=8, pady=6)
    scan_lf.grid(row=5, column=0, sticky="ew", padx=6, pady=(0, 4))
    scan_lf.columnconfigure(0, weight=1)

    v_move_mode   = tk.StringVar(value="steps_mm")
    v_step_x      = tk.StringVar(value="0.20")
    v_step_y      = tk.StringVar(value="0.20")
    v_orig_x      = tk.StringVar(value="0.0")
    v_orig_y      = tk.StringVar(value="0.0")
    v_settle_scan = tk.StringVar(value="0.20")
    v_nmax        = tk.StringVar(value="0")
    v_stop_err    = tk.IntVar(value=1)

    mode_f = tk.Frame(scan_lf); mode_f.pack(fill="x")
    tk.Label(mode_f, text="Modo movimiento:").pack(side="left")
    for txt, val in [("Pasos en mm", "steps_mm"), ("Escala px/mm del plan", "scale_px")]:
        tk.Radiobutton(mode_f, text=txt, variable=v_move_mode, value=val).pack(side="left", padx=4)

    steps_f = tk.Frame(scan_lf); steps_f.pack(fill="x", pady=2)
    for lbl, var in [("Paso X(mm):", v_step_x), ("Paso Y(mm):", v_step_y),
                     ("Origen X:", v_orig_x), ("Origen Y:", v_orig_y)]:
        tk.Label(steps_f, text=lbl).pack(side="left")
        tk.Entry(steps_f, textvariable=var, width=7).pack(side="left", padx=(2, 8))

    row0 = tk.Frame(scan_lf); row0.pack(fill="x", pady=2)
    for lbl, var, w in [("Settle(s):", v_settle_scan, 6), ("Max pts(0=todos):", v_nmax, 6)]:
        tk.Label(row0, text=lbl).pack(side="left")
        tk.Entry(row0, textvariable=var, width=w).pack(side="left", padx=(2, 10))
    tk.Checkbutton(row0, text="Stop on error", variable=v_stop_err).pack(side="left")

    axes_info = "sin stage"
    if stage is not None:
        axes_info = "%s | ejes: %s%s" % (
            stage.__class__.__name__, ", ".join(stage.AXES),
            " | Y invertido" if invert_y else "")
    tk.Label(scan_lf, text="Hardware: " + axes_info, fg="#555", anchor="w").pack(fill="x", pady=2)

    scan_btn_row = tk.Frame(scan_lf); scan_btn_row.pack(fill="x", pady=(4, 0))
    btn_scan_start = tk.Button(scan_btn_row, text="▶ INICIAR SCAN",
                               bg="#2e7d32", fg="white", width=16)
    btn_scan_stop  = tk.Button(scan_btn_row, text="⏹ DETENER", width=12, state="disabled")
    btn_scan_start.pack(side="left", padx=(0, 6))
    btn_scan_stop.pack(side="left", padx=(0, 6))

    preview_state = {"open": False}
    def _open_preview():
        if preview_state["open"]: return
        preview_state["open"] = True
        try:
            open_preview(svc=svc, parent_tk=ctrl, save_dir=images_dir,
                         base_name=sanitize_name(sample), autoscale=True,
                         max_update_fps=preview_fps, stage=stage, jog_step_mm=0.5,
                         on_close_cb=lambda: preview_state.update({"open": False}),
                         calibration=calibration)
        except Exception as e:
            preview_state["open"] = False
            messagebox.showerror("Preview", repr(e), parent=ctrl)

    tk.Button(scan_btn_row, text="📷 Preview", width=12,
              command=_open_preview).pack(side="left", padx=(0, 6))

    if stage_cam_desc is not None:
        from presentation.stage_viewer import open_stage_viewer
        tk.Button(scan_btn_row, text="🔭 Stage", width=10,
                  command=lambda: open_stage_viewer(
                      desc=stage_cam_desc, parent_tk=ctrl,
                      save_dir=images_dir)
                  ).pack(side="left", padx=(0, 6))

    def _load_prev_plan():
        path = filedialog.askopenfilename(
            title="Seleccioná un scan_plan.json anterior",
            initialdir=os.path.dirname(session_dir) if os.path.isdir(
                os.path.dirname(session_dir)) else os.path.expanduser("~"),
            filetypes=[("JSON plan", "scan_plan.json *.json"), ("Todos", "*.*")])
        if not path: return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            pts = data.get("points") or []
            if not pts:
                messagebox.showwarning("Plan anterior", "El archivo no tiene puntos.", parent=ctrl)
                return
            import shutil
            dst = os.path.join(session_dir, "scan_plan.json")
            shutil.copy2(path, dst)
            ui_log("📋 Plan anterior: %d puntos desde %s → copiado a sesión actual." % (
                len(pts), os.path.basename(path)))
            status.set("Plan cargado: %d puntos." % len(pts))
        except Exception as e:
            messagebox.showerror("Plan anterior", repr(e), parent=ctrl)

    tk.Button(scan_btn_row, text="📋 Plan anterior…", width=16,
              command=_load_prev_plan).pack(side="left", padx=(0, 6))

    def _load_scan_plan(path_override=None):
        p = path_override or os.path.join(session_dir, "scan_plan.json")
        if not os.path.exists(p):
            raise FileNotFoundError(
                "No se encontró scan_plan.json.\n"
                "Abrí el preview, definí el ROI y exportá el plan.\n"
                "O usá 'Plan anterior…' para cargar uno de otra sesión.")
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        pts = data.get("points") or []
        if not pts:
            raise ValueError("scan_plan.json no tiene puntos.")
        return p, pts, data

    def _on_progress(pr):
        icon = "✅" if pr.overall_ok else "⚠️"
        msg = "%s Punto %d ok=%s" % (icon, pr.point_index, pr.overall_ok)
        ctrl.after(0, lambda: ui_log(msg))
        ctrl.after(0, lambda: status.set(msg))

    def _on_finished(msg):
        ctrl.after(0, lambda: ui_log(msg))
        ctrl.after(0, lambda: status.set(msg))
        ctrl.after(0, lambda: btn_scan_start.configure(state="normal"))
        ctrl.after(0, lambda: btn_scan_stop.configure(state="disabled"))

    def scan_start():
        if runner_ref["runner"] and runner_ref["runner"].running: return
        try:
            path_plan, pts, _ = _load_scan_plan()
        except Exception as e:
            messagebox.showerror("Scan", repr(e), parent=ctrl); return

        nmax    = _num(v_nmax.get(), int, 0)
        settle  = _num(v_settle_scan.get(), float, 0.20)
        stop_er = bool(v_stop_err.get())
        laser_p = {"pulse_us": _num(v_p.get(), int, 0),
                   "delay_us": _num(v_d.get(), int, 0),
                   "trigger_mode": params.get("trigger_mode", "soft_delay"),
                   "n_pulsos": int(exp_cfg.get("laser", {}).get("n_pulsos", 1))}

        if v_move_mode.get() == "steps_mm":
            try:
                sx = float(v_step_x.get().replace(",", "."))
                sy = float(v_step_y.get().replace(",", "."))
                ox = float(v_orig_x.get().replace(",", "."))
                oy = float(v_orig_y.get().replace(",", "."))
                if sx <= 0 or sy <= 0: raise ValueError("pasos > 0")
            except Exception as e:
                messagebox.showerror("Scan", "Paso mm inválido: %s" % e, parent=ctrl); return
            def _px(p): return p.get("px", p.get("x", 0))
            def _py(p): return p.get("py", p.get("y", 0))
            xs = sorted(set(_px(p) for p in pts))
            ys = sorted(set(_py(p) for p in pts))
            cx = {v: i for i, v in enumerate(xs)}
            cy = {v: i for i, v in enumerate(ys)}
            pts = [{**p, "x_mm": round(ox + cx.get(_px(p), 0) * sx, 6),
                        "y_mm": round(oy + cy.get(_py(p), 0) * sy, 6)} for p in pts]
            ui_log("Modo pasos mm: %.3f×%.3f mm | origen=(%.3f, %.3f)" % (sx, sy, ox, oy))
        else:
            pts_mm = [p for p in pts if "x_mm" in p and "y_mm" in p]
            if pts_mm:
                pts = pts_mm
                ui_log("Usando mm del plan (%d puntos)." % len(pts))
            else:
                ui_log("⚠ Sin coordenadas mm. Exportá con calibración activa.")

        runner = ScanRunner(
            vc=svc, stage=stage,
            images_dir=images_dir, events_dir=events_dir,
            session_dir=session_dir,
            sample_name=sample, operator=operator,
            settle_s=settle, laser_params=laser_p, stop_on_error=stop_er,
            laser=laser,
            spectrometer=spectrometer,          # ← NUEVO
            spectrometer_params=exp_cfg.get("spectrometer", {}),
            use_sim_dwell=(laser is None),
            invert_y_axis=invert_y if invert_y else None,
        )
        runner.ctx.spectrum_viewer = spectrum_viewer
        runner.ctx.spectrometer_params["active_dark"] = active_dark[0]
        runner.on_progress = _on_progress
        runner.on_finished = _on_finished
        runner.on_log = lambda msg: ctrl.after(0, lambda: ui_log(msg))
        runner_ref["runner"] = runner
        btn_scan_start.configure(state="disabled")
        btn_scan_stop.configure(state="normal")
        ui_log("▶ SCAN %d pts | laser=%s | inv_y=%s | %s" % (
            len(pts), laser.__class__.__name__ if laser else "ninguno", invert_y, path_plan))
        status.set("Scan corriendo…")
        runner.start(pts, max_points=nmax)

    def scan_stop():
        r = runner_ref.get("runner")
        if r: r.stop()

    btn_scan_start.configure(command=scan_start)
    btn_scan_stop.configure(command=scan_stop)

    # ── Salir seguro ──────────────────────────────────────────────────────────
    exit_f = tk.Frame(frm, bd=1, relief="groove", pady=6)
    exit_f.grid(row=6, column=0, sticky="ew", padx=6, pady=(4, 4))

    def safe_exit_btn():
        if messagebox.askyesno("Salir seguro", "Cerrar microLIBS?", parent=ctrl):
            safe_shutdown()

    tk.Button(exit_f, text="🛑  SALIR SEGURO", width=20,
              bg="#b71c1c", fg="white", font=("", 10, "bold"),
              command=safe_exit_btn).pack(side="left", padx=10)
    tk.Label(exit_f, text="Detiene scan · apaga luz · desconecta láser · libera cámara y stage",
             fg="#555", anchor="w").pack(side="left", padx=6)

    ui_log("Sesión: %s" % session_dir)
    if svc.selected:
        ui_log("Cámara: %s" % svc.selected.label)
    if laser:
        ui_log("Láser: %s" % repr(laser))

    # ── PY-2: warning de mismatch láser/espectrómetro ─────────────────────────
    def _check_driver_mismatch():
        laser_drv = (params.get("laser_driver") or "").strip().lower()
        spec_drv  = (params.get("spectrometer_driver") or "").strip().lower()

        _SIM_LASER = {"sim", "sim_laser"}
        _REAL_LASER = {"ekspla"}
        _SIM_SPEC  = {"sim", "sim_spectrometer"}
        _REAL_SPEC = {"ocean", "ocean_optics", "libs2500"}

        msg = None
        if laser_drv in _REAL_LASER and spec_drv in _SIM_SPEC:
            msg = (
                "Combinación incoherente de drivers\n\n"
                "  Láser REAL  :  %s\n"
                "  Espectrómetro SIM  :  %s\n\n"
                "Los espectros guardados serán sintéticos (simulados),\n"
                "no del plasma real. ¿Olvidaste cambiar el driver a 'ocean'?\n\n"
                "Podés continuar — solo es un aviso."
            ) % (laser_drv, spec_drv)
        elif laser_drv in _SIM_LASER and spec_drv in _REAL_SPEC:
            msg = (
                "Combinación incoherente de drivers\n\n"
                "  Láser SIM  :  %s\n"
                "  Espectrómetro REAL  :  %s\n\n"
                "El espectrómetro esperará un trigger TTL que el SimLaser\n"
                "no genera. acquire() quedará bloqueado hasta timeout.\n\n"
                "Podés continuar — solo es un aviso."
            ) % (laser_drv, spec_drv)

        if msg:
            messagebox.showwarning("Mismatch de drivers", msg, parent=ctrl)

    ctrl.after(600, _check_driver_mismatch)



# ─── Panel de láser (widget interno) ─────────────────────────────────────────

def _build_laser_panel(parent_frm, grid_row: int, laser,
                       ui_log, status_var, ctrl_win,
                       spectrometer=None, session_dir=None, spectrum_viewer=None,
                       active_dark=None):
    """
    LabelFrame de control del láser.
    Si laser es None muestra mensaje informativo.
    """
    lbl = "Láser — %s" % laser.__class__.__name__ if laser else "Láser — ninguno configurado"
    lf = tk.LabelFrame(parent_frm, text=lbl, padx=8, pady=6)
    lf.grid(row=grid_row, column=0, sticky="ew", padx=6, pady=(0, 4))
    lf.columnconfigure(1, weight=1)

    if laser is None:
        tk.Label(lf,
                 text="Sin láser. Reiniciá la sesión y elegí 'ekspla' o 'sim_laser' en el wizard.",
                 fg="#888", font=("", 8), wraplength=560, justify="left").pack(anchor="w")
        return

    # ── Estado del espectrómetro (visible de un vistazo) ─────────────────────
    if spectrometer is None:
        spec_txt = "Espectrómetro: ninguno — los espectros no se adquirirán"
        spec_fg  = "#e65100"
    elif spectrometer.is_connected:
        spec_txt = "Espectrómetro: %s — conectado OK" % spectrometer.__class__.__name__
        spec_fg  = "#1b5e20" if "Sim" not in spectrometer.__class__.__name__ else "#1565c0"
    else:
        spec_txt = "Espectrómetro: %s — ERROR de conexión" % spectrometer.__class__.__name__
        spec_fg  = "#b71c1c"
    tk.Label(lf, text=spec_txt, fg=spec_fg, font=("", 9, "bold"),
             anchor="w").pack(fill="x", pady=(0, 4))

    # ── Indicadores de estado ─────────────────────────────────────────────────
    MOD_CPU = "CPU8000:16"

    v_power   = tk.StringVar(value="—")
    v_output  = tk.StringVar(value="—")
    v_fault   = tk.StringVar(value="—")
    v_reprate = tk.StringVar(value="—")

    st_row = tk.Frame(lf); st_row.pack(fill="x", pady=(0, 4))
    led_var = tk.StringVar(value="●")
    led_lbl = tk.Label(st_row, textvariable=led_var, font=("", 16), fg="#aaaaaa")
    led_lbl.pack(side="left", padx=(0, 6))

    for txt, var in [("Power:", v_power), ("Output:", v_output),
                     ("Fault:", v_fault), ("Rep.rate:", v_reprate)]:
        tk.Label(st_row, text=txt, font=("", 8)).pack(side="left", padx=(6, 2))
        tk.Label(st_row, textvariable=var, font=("", 8, "bold"),
                 width=9, anchor="w").pack(side="left")

    def _refresh_state():
        try:
            st = laser.get_state()
            pwr = st.get("power") or "?"
            out = st.get("output_enable") or "?"
            flt = st.get("fault_source") or "?"
            rr  = st.get("rep_rate_hz") or "?"
            color = "#2e7d32" if pwr == "ON" else ("#b71c1c" if pwr == "FAULT" else "#888888")
            ctrl_win.after(0, lambda: v_power.set(pwr))
            ctrl_win.after(0, lambda: v_output.set(out))
            ctrl_win.after(0, lambda: v_fault.set(flt))
            ctrl_win.after(0, lambda: v_reprate.set(rr))
            ctrl_win.after(0, lambda c=color: led_lbl.configure(fg=c))
            ui_log("Estado láser: Power=%s Output=%s Fault=%s Rep=%s Hz" % (pwr, out, flt, rr))
        except Exception as e:
            ctrl_win.after(0, lambda: v_power.set("ERR"))
            ui_log("❌ get_state: %s" % e)

    # ── Variables compartidas entre callbacks y widgets del panel ────────────
    v_fire_npulsos    = tk.StringVar(value="1")
    v_integration_ms  = tk.StringVar(value="5.0")
    v_delay_list      = tk.StringVar(value="0,2,5,10,20")
    last_spectrum     = [None]    # [dict | None] — último espectro adquirido
    _sweep_running    = [False]   # semáforo: impide barridos simultáneos
    _dark_status_var  = tk.StringVar(value="Sin fondo capturado")

    # ── Capturar fondo (dark) ────────────────────────────────────────────────
    def do_capture_dark():
        if not (spectrometer and spectrometer.is_connected):
            ui_log("Sin espectrómetro — no se puede capturar fondo.")
            return
        try: int_ms = max(2.1, float(v_integration_ms.get()))
        except Exception: int_ms = 5.0

        def _t():
            ui_log("Capturando fondo (modo free-running, %.1f ms)..." % int_ms)
            original_mode = getattr(spectrometer, "_sim_trigger_mode", None)
            try:
                spectrometer.set_trigger_mode(0)   # free-running: no espera TTL
                data = spectrometer.acquire(integration_ms=int_ms, averages=1)
                spectrometer.set_trigger_mode(3)   # restaurar modo LIBS
            except Exception as e:
                try: spectrometer.set_trigger_mode(3)
                except Exception: pass
                ui_log("Error capturando fondo: %s" % e)
                return

            if not (data and data.get("ok")):
                ui_log("Fondo: adquisición fallida.")
                return

            active_dark[0] = data.get("channels", {})
            n_ch = len(active_dark[0])
            ui_log("Fondo capturado — %d canal(es)." % n_ch)
            spectrum_viewer.update(data, "dark")

            import os, csv, datetime as _dt
            base = session_dir or "."
            out_dir = os.path.join(base, "spectra")
            os.makedirs(out_dir, exist_ok=True)
            ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = "fondo_%s.csv" % ts
            fpath = os.path.join(out_dir, fname)
            try:
                with open(fpath, "w", newline="", encoding="utf-8") as f:
                    wr = csv.writer(f)
                    wr.writerow(["channel", "wavelength_nm", "intensity"])
                    for ch_name, ch_data in sorted(active_dark[0].items()):
                        for wl, it in zip(ch_data.get("wavelengths", []),
                                          ch_data.get("intensities", [])):
                            wr.writerow([ch_name, "%.4f" % wl, "%.2f" % it])
                ui_log("Fondo guardado: %s" % fpath)
                ctrl_win.after(0, lambda: _dark_status_var.set(
                    "Fondo activo: %s (%d ch)" % (fname, n_ch)))
                status_var.set("Fondo activo. Próxima adquisición incluirá resta.")
            except Exception as e:
                ui_log("Error guardando fondo: %s" % e)

        threading.Thread(target=_t, daemon=True).start()

    dark_row = tk.Frame(lf); dark_row.pack(fill="x", pady=(0, 2))
    tk.Button(dark_row, text="🌑 Capturar fondo", bg="#37474f", fg="white",
              command=do_capture_dark).pack(side="left", padx=(0, 8))
    tk.Label(dark_row, textvariable=_dark_status_var,
             fg="#888", font=("", 8)).pack(side="left")

    # ── ARM / DISARM / FIRE + ADQUIRIR ───────────────────────────────────────
    ctrl_row = tk.Frame(lf); ctrl_row.pack(fill="x", pady=2)

    def do_arm():
        def _t():
            try:
                laser.arm()
                ui_log("✅ Láser ARMADO.")
                status_var.set("Láser ARMADO.")
                _refresh_state()
            except Exception as e:
                ui_log("❌ arm: %s" % e); status_var.set("arm falló.")
        threading.Thread(target=_t, daemon=True).start()

    def do_disarm():
        def _t():
            try:
                laser.disarm()
                ui_log("Láser desarmado.")
                status_var.set("Láser desarmado.")
                _refresh_state()
            except Exception as e:
                ui_log("❌ disarm: %s" % e)
        threading.Thread(target=_t, daemon=True).start()

    def _fire_acquire_core(n, int_ms, log_fn=None):
        """
        Secuencia bloqueante de 4 pasos: configurar → armar → disparar → esperar.
        Llamar siempre en un hilo daemon, nunca en el hilo de UI.
        Retorna (spectrum_dict | None, fire_ok: bool, fire_result: dict).
        """
        if log_fn is None:
            log_fn = ui_log

        # 1/4 — configurar integración
        log_fn("1/4 Integracion: %.1f ms | %d pulsos" % (int_ms, n))
        if spectrometer and spectrometer.is_connected:
            try:
                spectrometer.set_integration(max(2100, int(int_ms * 1000)))
            except Exception as e:
                log_fn("WARN set_integration: %s" % e)

        # 2/4 — armar adquisición ANTES del disparo
        acq = {"data": None, "error": None}
        acq_thread = None
        if spectrometer and spectrometer.is_connected:
            log_fn("2/4 Espectrómetro armado — esperando trigger TTL...")
            def _acquire():
                try:
                    acq["data"] = spectrometer.acquire(
                        integration_ms=int_ms, averages=1)
                except Exception as e:
                    acq["error"] = str(e)
            acq_thread = threading.Thread(target=_acquire, daemon=True)
            acq_thread.start()
        else:
            log_fn("2/4 Sin espectrómetro — solo disparo.")

        # 3/4 — disparar
        log_fn("3/4 Disparando %d pulso(s)..." % n)
        fire_ok = False
        fire_result = {}
        try:
            fire_result = laser.fire_burst(n)
            diag = fire_result.get("diag", {})
            if diag:
                log_fn("[diag] OE_rb=%s  BM_post=%s" % (
                    diag.get("oe_readback", "?"),
                    diag.get("bm_post_trigger", "?")))
            fire_ok = bool(fire_result.get("ok"))
        except Exception as e:
            fire_result = {"ok": False, "error": str(e)}
            log_fn("❌ FIRE excepción: %s" % e)

        # 4/4 — esperar espectro
        spectrum = None
        if acq_thread is not None:
            timeout_s = int_ms / 1000.0 + 35.0  # 35 s extra para warmup del flashlamp
            acq_thread.join(timeout=timeout_s)
            if acq["data"] and acq["data"].get("ok"):
                spectrum = acq["data"]
                n_ch = len(spectrum.get("channels", {}))
                log_fn("4/4 Espectro OK — %d canal(es)." % n_ch)
            elif acq["error"]:
                log_fn("4/4 Error espectro: %s" % acq["error"])
            elif acq_thread.is_alive():
                log_fn("4/4 Timeout (%.0f s) — trigger no llegó." % timeout_s)
            else:
                log_fn("4/4 Espectro con error interno.")

        return spectrum, fire_ok, fire_result

    def do_fire():
        try: n = max(1, int(v_fire_npulsos.get()))
        except Exception: n = 1
        try: int_ms = max(2.1, float(v_integration_ms.get()))
        except Exception: int_ms = 5.0

        def _blink_sequence(step=0):
            colors = ["#ffff00", "#ffffff", "#ffff00", "#ffffff",
                      "#ffff00", "#ff8800", "#ffff00"]
            if step < len(colors):
                try:
                    led_lbl.configure(fg=colors[step])
                except Exception:
                    return
                ctrl_win.after(90, lambda: _blink_sequence(step + 1))

        ctrl_win.after(0, lambda: _blink_sequence(0))

        def _t():
            spectrum, fire_ok, fire_result = _fire_acquire_core(n, int_ms)
            if fire_ok:
                msg = "🔥 FIRE OK | %d pulsos | %.1f ms" % (
                    fire_result.get("n_pulsos", n), fire_result.get("elapsed_ms", 0))
                ui_log(msg); status_var.set(msg)
                ctrl_win.after(700, lambda: led_lbl.configure(fg="#00e676"))
            else:
                err_msg = fire_result.get("error", "desconocido")
                ui_log("❌ FIRE: %s" % err_msg)
                status_var.set("FIRE falló: %s" % err_msg)
                ctrl_win.after(700, lambda: led_lbl.configure(fg="#f44336"))
            if spectrum is not None:
                last_spectrum[0] = spectrum
                status_var.set("Espectro listo. Guardá con el botón abajo.")
            ctrl_win.after(1200, lambda: threading.Thread(
                target=_refresh_state, daemon=True).start())

        threading.Thread(target=_t, daemon=True).start()

    tk.Button(ctrl_row, text="ARM",    width=9, bg="#1565c0", fg="white",
              command=do_arm).pack(side="left", padx=(0, 4))
    tk.Button(ctrl_row, text="DISARM", width=9, bg="#e65100", fg="white",
              command=do_disarm).pack(side="left", padx=(0, 12))
    tk.Label(ctrl_row, text="N pulsos:").pack(side="left")
    tk.Entry(ctrl_row, textvariable=v_fire_npulsos, width=5).pack(side="left", padx=(2, 4))
    tk.Label(ctrl_row, text="Integ (ms):").pack(side="left", padx=(6, 0))
    tk.Entry(ctrl_row, textvariable=v_integration_ms, width=6).pack(side="left", padx=(2, 6))
    tk.Button(ctrl_row, text="🔥 FIRE + ADQUIRIR", bg="#b71c1c", fg="white",
              command=do_fire).pack(side="left", padx=(0, 10))
    tk.Button(ctrl_row, text="🔄 Leer estado", width=14,
              command=lambda: threading.Thread(
                  target=_refresh_state, daemon=True).start()).pack(side="left")
    if spectrum_viewer is not None:
        tk.Button(ctrl_row, text="📊 Ver espectro", bg="#5e35b1", fg="white",
                  command=spectrum_viewer.show).pack(side="left", padx=(4, 0))

    # ── Parámetros configurables ──────────────────────────────────────────────
    params_lf = tk.LabelFrame(lf, text="Parámetros NL230", padx=6, pady=4)
    params_lf.pack(fill="x", pady=(6, 0))

    REGS = [
        ("Output Energy level",  MOD_CPU, "Output Energy level",                     11),
        ("Frequency divider",    MOD_CPU, "Frequency divider",                       8),
        ("QSW delay (µs)",       MOD_CPU, "QSW Adjustment output level delay",       8),
        ("Burst length",         MOD_CPU, "Burst length",                            8),
        ("Burst mode",           MOD_CPU, "Continuous / Burst mode / Trigger burst", 14),
        ("Sync mode",            MOD_CPU, "Synchronization mode",                    14),
        ("Output enable",        MOD_CPU, "Output enable",                           8),
        ("Repetition rate (Hz)", MOD_CPU, "Repetition rate",                         8),
    ]

    reg_vars = {}  # label → (StringVar, module, register)

    def _read_reg(label, module, register, var):
        def _t():
            try:
                val = laser.get_register(module, register)
                ctrl_win.after(0, lambda: var.set(val))
                ui_log("Leer %s = %s" % (label, val))
            except Exception as e:
                ctrl_win.after(0, lambda: var.set("ERR"))
                ui_log("❌ leer %s: %s" % (label, e))
        threading.Thread(target=_t, daemon=True).start()

    def _write_reg(label, module, register, var):
        val = var.get().strip()
        if not val or val in ("—", "ERR"):
            messagebox.showwarning("Set registro",
                "Primero usá 'Leer', modificá el valor y luego 'Set'.",
                parent=ctrl_win)
            return
        if not messagebox.askyesno("Confirmar Set",
                "¿Escribir  %s = %s ?" % (label, val), parent=ctrl_win):
            return
        def _t():
            try:
                laser.set_register(module, register, val)
                ui_log("✅ Set %s = %s" % (label, val))
                status_var.set("Set %s = %s" % (label, val))
                _read_reg(label, module, register, var)
            except Exception as e:
                ui_log("❌ set %s: %s" % (label, e))
        threading.Thread(target=_t, daemon=True).start()

    for i, (lbl, mod, reg, width) in enumerate(REGS):
        rr, cc = divmod(i, 2)
        col = cc * 4
        tk.Label(params_lf, text=lbl + ":", anchor="e",
                 font=("", 8), width=22).grid(row=rr, column=col,
                                              sticky="e", padx=(6, 2), pady=2)
        v = tk.StringVar(value="—")
        reg_vars[lbl] = (v, mod, reg)
        tk.Entry(params_lf, textvariable=v, width=width,
                 font=("", 8)).grid(row=rr, column=col+1, sticky="w", padx=2)
        tk.Button(params_lf, text="Leer", font=("", 7), width=5,
                  command=lambda lb=lbl, m=mod, r=reg, vv=v: _read_reg(lb, m, r, vv)
                  ).grid(row=rr, column=col+2, padx=2)
        tk.Button(params_lf, text="Set", font=("", 7), width=4,
                  command=lambda lb=lbl, m=mod, r=reg, vv=v: _write_reg(lb, m, r, vv)
                  ).grid(row=rr, column=col+3, padx=(0, 8))

    def read_all_params():
        def _t():
            for lbl2, (v2, m2, r2) in reg_vars.items():
                try:
                    val = laser.get_register(m2, r2)
                    ctrl_win.after(0, lambda vv=v2, vval=val: vv.set(vval))
                except Exception:
                    ctrl_win.after(0, lambda vv=v2: vv.set("ERR"))
            ui_log("Parámetros actualizados.")
        threading.Thread(target=_t, daemon=True).start()

    # ── Guardar espectro (raw + neto si hay fondo) ───────────────────────────
    def _write_channels_csv(fpath, channels_dict):
        """Escribe CSV channel/wavelength_nm/intensity para un dict de canales."""
        import csv as _csv
        with open(fpath, "w", newline="", encoding="utf-8") as f:
            wr = _csv.writer(f)
            wr.writerow(["channel", "wavelength_nm", "intensity"])
            for ch_name, ch_data in sorted(channels_dict.items()):
                for wl, it in zip(ch_data.get("wavelengths", []),
                                  ch_data.get("intensities", [])):
                    wr.writerow([ch_name, "%.4f" % wl, "%.6f" % it])

    def do_save_spectrum():
        sp = last_spectrum[0]
        if sp is None:
            messagebox.showinfo("Guardar espectro",
                "Todavía no hay espectro. Usá 'FIRE + ADQUIRIR' primero.",
                parent=ctrl_win)
            return

        import os, datetime
        from spec_pipeline import subtract_dark as _subtract_dark

        base = session_dir or "."
        out_dir = os.path.join(base, "spectra")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        raw_channels = sp.get("channels", {})

        # ── Guardar raw ──────────────────────────────────────────────────────
        raw_path = os.path.join(out_dir, "espectro_%s.csv" % ts)
        try:
            _write_channels_csv(raw_path, raw_channels)
            ui_log("Raw guardado: %s" % raw_path)
        except Exception as e:
            ui_log("Error guardando raw: %s" % e)
            return

        # ── Restar fondo si está activo ──────────────────────────────────────
        net_channels = None
        if active_dark[0]:
            dark = active_dark[0]
            net_channels = {}
            for ch_name, raw_ch in sorted(raw_channels.items()):
                dark_ch = dark.get(ch_name)
                if dark_ch is None:
                    ui_log("WARN canal %s: sin fondo correspondiente, se omite del neto." % ch_name)
                    continue
                try:
                    net_ch = _subtract_dark(raw_ch, dark_ch, clip_negative=False)
                    net_ch["channel"] = ch_name
                    net_channels[ch_name] = net_ch
                except Exception as e:
                    ui_log("Error restando fondo canal %s: %s" % (ch_name, e))

            if net_channels:
                net_path = os.path.join(out_dir, "espectro_neto_%s.csv" % ts)
                try:
                    _write_channels_csv(net_path, net_channels)
                    ui_log("Neto guardado: %s" % net_path)
                    status_var.set("Guardados: raw + neto (%d ch)" % len(net_channels))
                except Exception as e:
                    ui_log("Error guardando neto: %s" % e)
            else:
                ui_log("Sin canales netos — fondo no coincidió con señal.")
        else:
            ui_log("Sin fondo activo, no se resta. Solo raw guardado.")
            status_var.set("Guardado raw: espectro_%s.csv" % ts)

        # ── Gráfico: neto si existe, else raw ────────────────────────────────
        plot_data = net_channels if net_channels else raw_channels
        plot_title = ("Espectro neto (raw − fondo) — %s" % ts
                      if net_channels else "Espectro raw — %s" % ts)
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(10, 4))
            colors = {"A": "#1565c0", "B": "#2e7d32", "C": "#b71c1c", "D": "#FF0000"}
            for ch_name, ch_data in sorted(plot_data.items()):
                ax.plot(ch_data.get("wavelengths", []),
                        ch_data.get("intensities", []),
                        label="Canal %s" % ch_name,
                        color=colors.get(ch_name, None), lw=0.8)
            if net_channels:
                ax.axhline(0, color="#555", lw=0.5, ls="--")
            ax.set_xlabel("Longitud de onda (nm)")
            ax.set_ylabel("Intensidad (cuentas)")
            ax.set_title(plot_title)
            ax.legend()
            fig.tight_layout()
            plt.show(block=False)
        except Exception as e:
            ui_log("Matplotlib no disponible: %s" % e)

    # ── Barrido de delay ──────────────────────────────────────────────────────
    def do_delay_sweep():
        if _sweep_running[0]:
            messagebox.showwarning("Barrido de delay",
                "Ya hay un barrido en curso.", parent=ctrl_win)
            return

        # Verificar soporte
        if not (spectrometer and spectrometer.is_connected
                and spectrometer.supports_acquisition_delay()):
            messagebox.showinfo("Barrido de delay",
                "El espectrómetro conectado no soporta delay de adquisición.\n"
                "Con SimSpectrometer está habilitado. Con HR2000+ real, la feature\n"
                "no está implementada en pyseabreeze para este modelo.",
                parent=ctrl_win)
            return

        # Parsear lista de delays
        raw = v_delay_list.get().strip()
        delays = []
        try:
            for tok in raw.replace(";", ",").split(","):
                tok = tok.strip()
                if not tok:
                    continue
                # Acepta "min/max/paso" como rango
                if "/" in tok:
                    parts = tok.split("/")
                    mn2, mx2, step2 = int(parts[0]), int(parts[1]), int(parts[2])
                    delays += list(range(mn2, mx2 + 1, max(1, step2)))
                else:
                    delays.append(int(tok))
        except Exception as e:
            messagebox.showerror("Barrido de delay",
                "No se pudo parsear la lista de delays.\n"
                "Formato: '0,2,5,10,20'  o  '0/20/5' (min/max/paso)\n"
                "Error: %s" % e, parent=ctrl_win)
            return

        if not delays:
            messagebox.showwarning("Barrido de delay",
                "La lista de delays está vacía.", parent=ctrl_win)
            return

        # Límites del equipo
        mn_lim, mx_lim, inc_lim = spectrometer.get_acquisition_delay_limits_us()
        delays_valid = [d for d in delays if mn_lim <= d <= (mx_lim or d)]
        if len(delays_valid) < len(delays):
            fuera = [d for d in delays if d not in delays_valid]
            ui_log("WARN delays fuera de rango ignorados: %s" % fuera)
        if not delays_valid:
            messagebox.showwarning("Barrido de delay",
                "Todos los delays están fuera del rango del equipo (%d–%d µs)."
                % (mn_lim, mx_lim), parent=ctrl_win)
            return

        try: n = max(1, int(v_fire_npulsos.get()))
        except Exception: n = 1
        try: int_ms = max(2.1, float(v_integration_ms.get()))
        except Exception: int_ms = 5.0

        # Pre-flight: verificar estado del láser
        laser_warn = ""
        try:
            st = laser.get_state()
            armed = str(st.get("power", "")).upper() in ("ON", "TRUE", "1")
            if not armed:
                laser_warn = "\n⚠ ATENCIÓN: el láser NO está armado (ARM primero).\n"
        except Exception:
            pass

        total_disparos = len(delays_valid) * n
        resumen = (
            "Barrido de delay de adquisición\n"
            "%s\n"
            "Delays: %s µs\n"
            "N pulsos por delay: %d\n"
            "Integración: %.1f ms\n"
            "Total de disparos: %d\n\n"
            "¿Continuar?"
        ) % (laser_warn, delays_valid, n, int_ms, total_disparos)

        if not messagebox.askyesno("Confirmar barrido", resumen, parent=ctrl_win):
            return

        import os, csv, datetime as _dt

        def _run_sweep():
            _sweep_running[0] = True
            base = session_dir or "."
            sweep_ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            out_dir = os.path.join(base, "spectra", "sweep_%s" % sweep_ts)
            os.makedirs(out_dir, exist_ok=True)
            ui_log("Barrido iniciado — %d puntos → %s" % (len(delays_valid), out_dir))
            status_var.set("Barrido en curso...")

            sweep_spectra = []   # [(delay_us, spectrum_dict)]
            saved_paths   = []

            for i, delay_us in enumerate(delays_valid):
                ui_log("--- Delay %d µs (%d/%d) ---" % (delay_us, i + 1, len(delays_valid)))
                try:
                    spectrometer.set_acquisition_delay_us(delay_us)
                except Exception as e:
                    ui_log("WARN set_delay %d µs: %s" % (delay_us, e))

                spectrum, fire_ok, fire_result = _fire_acquire_core(
                    n, int_ms,
                    log_fn=lambda msg, d=delay_us: ui_log("[delay=%dµs] %s" % (d, msg))
                )

                if not fire_ok:
                    fire_err = fire_result.get("error", "desconocido")
                    ui_log("ERROR disparo delay=%d µs: %s" % (delay_us, fire_err))
                    # No abortar: seguir el barrido aunque el láser falle (p. ej. no armado).
                    # El espectro generado sin disparo real se descarta para no contaminar datos.
                    if spectrum is not None:
                        ui_log("  (espectro descartado — el láser no disparó)")
                    continue

                # Guardar CSV con delay en el nombre
                if spectrum is not None:
                    sweep_spectra.append((delay_us, spectrum))
                    last_spectrum[0] = spectrum
                    fname = "spectrum_delay%06dus_%s.csv" % (delay_us, sweep_ts)
                    fpath = os.path.join(out_dir, fname)
                    channels = spectrum.get("channels", {})
                    try:
                        with open(fpath, "w", newline="", encoding="utf-8") as f:
                            wr = csv.writer(f)
                            wr.writerow(["delay_us", "channel",
                                         "wavelength_nm", "intensity"])
                            for ch_name, ch_data in sorted(channels.items()):
                                wls = ch_data.get("wavelengths", [])
                                its = ch_data.get("intensities", [])
                                for wl, it in zip(wls, its):
                                    wr.writerow([delay_us, ch_name,
                                                 "%.4f" % wl, "%.2f" % it])
                        saved_paths.append(fpath)
                        ui_log("Guardado: %s" % fpath)
                    except Exception as e:
                        ui_log("Error guardando delay=%d µs: %s" % (delay_us, e))
                else:
                    ui_log("Sin espectro para delay=%d µs." % delay_us)

            ui_log("Barrido completo — %d/%d puntos con espectro." % (
                len(sweep_spectra), len(delays_valid)))
            status_var.set("Barrido completo. %d espectros en %s" % (
                len(sweep_spectra), out_dir))
            _sweep_running[0] = False

            # Gráfico comparativo — delegar al hilo UI para que no se cierre
            if len(sweep_spectra) >= 2:
                ctrl_win.after(0, lambda ss=list(sweep_spectra), ts=sweep_ts:
                               _show_sweep_plot(ss, ts))

        def _show_sweep_plot(sweep_spectra, sweep_ts):
            try:
                import matplotlib.pyplot as plt
                import matplotlib.cm as cm

                ch_names = sorted(sweep_spectra[0][1].get("channels", {}).keys())
                n_ch = len(ch_names)
                if n_ch == 0:
                    return
                fig, axes = plt.subplots(1, n_ch, figsize=(5 * n_ch, 4),
                                         squeeze=False)
                colormap = cm.get_cmap("plasma", len(sweep_spectra))

                for col_i, ch_name in enumerate(ch_names):
                    ax = axes[0][col_i]
                    for k, (delay_us, sp) in enumerate(sweep_spectra):
                        ch_data = sp.get("channels", {}).get(ch_name, {})
                        wls = ch_data.get("wavelengths", [])
                        its = ch_data.get("intensities", [])
                        if wls and its:
                            ax.plot(wls, its,
                                    label="%d µs" % delay_us,
                                    color=colormap(k), lw=0.8, alpha=0.85)
                    ax.set_xlabel("Longitud de onda (nm)")
                    ax.set_ylabel("Intensidad (cuentas)")
                    ax.set_title("Canal %s" % ch_name)
                    ax.legend(fontsize=7, title="delay acq.")

                fig.suptitle("Barrido de delay de adquisición — %s" % sweep_ts)
                fig.tight_layout()
                plt.show(block=True)
            except Exception as e:
                ui_log("Matplotlib no disponible para gráfico comparativo: %s" % e)

        threading.Thread(target=_run_sweep, daemon=True).start()

    sweep_row = tk.Frame(lf); sweep_row.pack(fill="x", pady=(4, 0))
    _sweep_lbl_prefix = "Delays (µs):"
    _no_delay_note = " (no soportado por este equipo)"

    def _update_sweep_btn_state():
        supported = bool(spectrometer and spectrometer.is_connected
                         and spectrometer.supports_acquisition_delay())
        state = "normal" if supported else "disabled"
        try:
            _sweep_btn.config(state=state)
            _sweep_note_lbl.config(
                text="" if supported else _no_delay_note, fg="#888")
        except Exception:
            pass
        ctrl_win.after(2000, _update_sweep_btn_state)

    tk.Label(sweep_row, text=_sweep_lbl_prefix).pack(side="left")
    tk.Entry(sweep_row, textvariable=v_delay_list, width=20).pack(
        side="left", padx=(2, 6))
    _sweep_btn = tk.Button(sweep_row, text="📊 Barrido de delay",
                           bg="#4a148c", fg="white",
                           command=do_delay_sweep)
    _sweep_btn.pack(side="left", padx=(0, 6))
    _sweep_note_lbl = tk.Label(sweep_row, text="", fg="#888", font=("", 8))
    _sweep_note_lbl.pack(side="left")
    ctrl_win.after(500, _update_sweep_btn_state)

    ttk.Separator(lf, orient="horizontal").pack(fill="x", padx=4, pady=(6, 2))

    save_row = tk.Frame(lf); save_row.pack(fill="x", pady=(6, 2))
    tk.Button(save_row, text="💾 Guardar espectro", bg="#1b5e20", fg="white",
              command=do_save_spectrum).pack(side="left", padx=4)
    tk.Label(save_row, text="Exporta CSV + abre gráfico del último espectro adquirido.",
             fg="#555", font=("", 8)).pack(side="left", padx=6)

    bottom_row = tk.Frame(lf); bottom_row.pack(fill="x", pady=(4, 0))
    tk.Button(bottom_row, text="🔄 Leer todos los parámetros",
              command=read_all_params).pack(side="left", padx=4)
    tk.Label(bottom_row,
             text="⚠ Escribir parámetros solo con Power=OFF. Output enable sí se puede "
                  "cambiar con el láser armado.",
             fg="#8a4a00", font=("", 7), wraplength=400, justify="left"
             ).pack(side="left", padx=8)

    # Auto-leer estado al abrir
    threading.Thread(target=_refresh_state, daemon=True).start()
