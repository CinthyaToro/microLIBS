# -*- coding: utf-8 -*-
"""
presentation/stage_viewer.py
=============================
Ventana flotante con la vista en vivo de la cámara de stage.
Solo video + botón de foto. No bloquea al llamador.
"""
from __future__ import annotations
import os
import threading
import time

import cv2
from PIL import Image, ImageTk
from service.vision_service import CameraDescriptor


def open_stage_viewer(desc: CameraDescriptor, parent_tk,
                      save_dir: str | None = None) -> None:
    """
    Abre la ventana de stage. Retorna inmediatamente (no bloquea).
    desc=None cierra silenciosamente.
    """
    if desc is None:
        return

    import tkinter as tk
    from tkinter import messagebox

    backend = _make_backend(desc)

    win = tk.Toplevel(parent_tk)
    win.title("Stage — %s" % desc.label)
    win.geometry("700x560")
    win.resizable(True, True)

    state = {"alive": True, "last_frame": None, "imref": None}

    # ── Canvas de video ───────────────────────────────────────────────────────
    canvas = tk.Canvas(win, bg="#111", cursor="crosshair")
    canvas.pack(fill="both", expand=True)

    # ── Barra inferior ────────────────────────────────────────────────────────
    bar = tk.Frame(win)
    bar.pack(fill="x", padx=8, pady=(2, 6))

    info_var = tk.StringVar(value="Conectando…")
    tk.Label(bar, textvariable=info_var, anchor="w",
             fg="#333").pack(side="left", fill="x", expand=True)

    photo_n = {"n": 0}

    def _take_photo():
        frame = state.get("last_frame")
        if frame is None:
            messagebox.showwarning("Foto", "Todavía no hay imagen.", parent=win)
            return
        if not save_dir:
            messagebox.showinfo("Foto",
                "save_dir no configurado — la foto no se guarda.", parent=win)
            return
        photo_n["n"] += 1
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = "stage_%s_%03d.png" % (ts, photo_n["n"])
        path = os.path.join(save_dir, fname)
        try:
            os.makedirs(save_dir, exist_ok=True)
            cv2.imwrite(path, frame)
            info_var.set("Foto guardada: %s" % fname)
        except Exception as e:
            messagebox.showerror("Foto", "Error al guardar: %s" % e, parent=win)

    tk.Button(bar, text="📷 Foto", width=10, command=_take_photo).pack(side="right")

    # ── Hilo de captura ───────────────────────────────────────────────────────
    def _capture():
        try:
            backend.open()
            if backend.needs_streaming:
                backend.start_capture()
            # Descartar primeros frames de webcam
            n_warmup = 6 if desc.kind == "opencv" else 0
            for _ in range(n_warmup):
                if not state["alive"]:
                    return
                try:
                    backend.read_frame_bgr()
                except Exception:
                    pass
                time.sleep(0.05)

            while state["alive"]:
                try:
                    f = backend.read_frame_bgr()
                    if f is not None and f.size > 0:
                        state["last_frame"] = f
                except Exception:
                    time.sleep(0.2)
                time.sleep(0.08)   # ~12 fps
        except Exception as e:
            state["last_frame"] = None
            state["err"] = str(e)
        finally:
            try:
                backend.close()
            except Exception:
                pass

    threading.Thread(target=_capture, daemon=True).start()

    # ── Loop de display (win.after) ───────────────────────────────────────────
    def _update():
        if not state["alive"]:
            return
        try:
            if not win.winfo_exists():
                return
        except Exception:
            return

        frame = state.get("last_frame")
        err   = state.get("err")

        if err and frame is None:
            info_var.set("Error: %s" % err)
        elif frame is not None:
            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            if cw > 50 and ch > 50:
                h, w = frame.shape[:2]
                scale = min(cw / w, ch / h)
                nw, nh = int(w * scale), int(h * scale)
                small  = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
                rgb    = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                # ImageTk.PhotoImage se crea en el hilo principal (Tkinter thread-safety)
                imgtk  = ImageTk.PhotoImage(image=Image.fromarray(rgb))
                state["imref"] = imgtk   # mantener ref para evitar GC
                offx = (cw - nw) // 2
                offy = (ch - nh) // 2
                canvas.delete("all")
                canvas.create_image(offx, offy, anchor="nw", image=imgtk)
                info_var.set("%s | %d×%d" % (desc.label, w, h))

        win.after(100, _update)   # 10 fps

    win.after(300, _update)   # dar tiempo al hilo de captura para el warmup

    # ── Cierre ────────────────────────────────────────────────────────────────
    def _close():
        state["alive"] = False
        try:
            win.destroy()
        except Exception:
            pass

    win.protocol("WM_DELETE_WINDOW", _close)


# ── Backend HAL ───────────────────────────────────────────────────────────────

def _make_backend(desc: CameraDescriptor):
    from hal.factory import create_camera
    return create_camera(desc.kind, serial=desc.id, index=desc.id)
