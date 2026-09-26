# -*- coding: utf-8 -*-
"""
presentation/camera_selector.py
================================
Diálogo Tkinter para asignar cámaras a los roles MUESTRA y STAGE.
Retorna {"muestra": CameraDescriptor, "stage": CameraDescriptor | None}.
"""
from __future__ import annotations
import threading
import time

import cv2
from PIL import Image, ImageTk
from service.vision_service import CameraDescriptor, VisionService

_STAGE_NONE_LABEL = "-- ninguna --"
_STAGE_SIM_LABEL  = "Simulada (sim_camera)"


def select_camera_gui(svc: VisionService, parent_tk=None) -> dict:
    """
    Abre un diálogo para asignar cámaras a los roles MUESTRA y STAGE.
    Retorna {"muestra": CameraDescriptor, "stage": CameraDescriptor | None}.
    Lanza RuntimeError si se cancela.
    """
    import tkinter as tk
    from tkinter import messagebox

    root = parent_tk if parent_tk is not None else tk.Tk()
    created_root = parent_tk is None
    if created_root:
        root.withdraw()

    win = tk.Toplevel(root)
    win.title("Seleccionar cámaras — microLIBS")
    win.geometry("880x560")
    win.resizable(True, True)

    result = {"muestra": None, "stage": None}

    # ── Backend temporal para preview ────────────────────────────────────────

    def _make_temp_backend(desc):
        from hal.factory import create_camera
        return create_camera(
            desc.kind,
            serial=desc.id,
            dll_dir=svc.dll_dir,
            index=desc.id,
            warmup_frames=3,
        )

    # ── Panel reutilizable: dropdown + thumbnail + info ──────────────────────

    class PreviewPanel:
        THUMB_W       = 280
        THUMB_H       = 210
        N_WARMUP_OPCV = 6    # frames a descartar; OpenCV devuelve negro los primeros frames
        N_RETRIES     = 8

        def __init__(self, parent, title):
            frame = tk.LabelFrame(parent, text=title, padx=8, pady=8)
            frame.pack(side="left", fill="both", expand=True, padx=8, pady=8)
            self._frame    = frame
            self._gen      = 0
            self._desc     = None
            self._label_to_desc = {}
            self._menu_var = tk.StringVar(value="")

            # Dropdown
            self._menu_frame = tk.Frame(frame)
            self._menu_frame.pack(fill="x", pady=(0, 6))

            # Contenedor de tamaño fijo en píxeles.
            # pack_propagate(False) evita que el Label interno (cuyos width/height
            # son en caracteres cuando no hay imagen) deforme el layout.
            thumb_box = tk.Frame(frame, width=self.THUMB_W, height=self.THUMB_H,
                                 bg="#222")
            thumb_box.pack_propagate(False)
            thumb_box.pack()
            self.thumb_lbl = tk.Label(thumb_box, bg="#222")
            self.thumb_lbl.place(relwidth=1, relheight=1)

            # Info
            self.info_var = tk.StringVar(value="Seleccioná una cámara.")
            tk.Label(frame, textvariable=self.info_var, wraplength=270,
                     justify="left", anchor="nw", fg="#444").pack(fill="x", pady=4)

            # Refresh manual
            self.btn_refresh = tk.Button(frame, text="↺ Actualizar preview",
                                         state="disabled", width=18)
            self.btn_refresh.pack(pady=2)

        def rebuild_menu(self, options, extra_top=None):
            """
            options:   [(label, CameraDescriptor), ...]
            extra_top: [(label, None), ...] insertados al inicio
            """
            for w in self._menu_frame.winfo_children():
                w.destroy()

            all_opts = list(extra_top or []) + list(options)
            if not all_opts:
                tk.Label(self._menu_frame, text="(ninguna cámara detectada)",
                         fg="#888").pack()
                self._desc = None
                return

            self._label_to_desc = {lbl: desc for lbl, desc in all_opts}
            labels = [lbl for lbl, _ in all_opts]
            if self._menu_var.get() not in labels:
                self._menu_var.set(labels[0])

            def _on_change(*_):
                lbl  = self._menu_var.get()
                desc = self._label_to_desc.get(lbl)
                self._desc = desc
                if desc is not None:
                    self.btn_refresh.configure(
                        state="normal",
                        command=lambda d=desc: self.launch_preview(d))
                    self.launch_preview(desc)
                else:
                    self.cancel()
                    self.thumb_lbl.configure(image="", bg="#222")
                    self.thumb_lbl.imgtk = None
                    self.info_var.set("Sin cámara de stage.")
                    self.btn_refresh.configure(state="disabled")

            om = tk.OptionMenu(self._menu_frame, self._menu_var, *labels,
                               command=_on_change)
            om.configure(width=34)
            om.pack(fill="x")
            _on_change()   # dispara preview del valor inicial

        def launch_preview(self, desc):
            self._gen += 1
            gen = self._gen
            self.thumb_lbl.configure(image="", bg="#333")
            self.thumb_lbl.imgtk = None
            self.info_var.set("Cargando preview…")
            self.btn_refresh.configure(state="normal",
                                       command=lambda d=desc: self.launch_preview(d))
            threading.Thread(target=lambda: self._grab_thumb(desc, gen),
                             daemon=True).start()

        def cancel(self):
            """Invalida cualquier hilo de preview en vuelo."""
            self._gen += 1

        @property
        def selected_desc(self):
            return self._desc

        def _grab_thumb(self, desc, gen):
            """
            Corre en hilo daemon.
            PIL Image se prepara aquí; ImageTk.PhotoImage se crea en _update_ui
            (hilo principal) porque Tkinter no es thread-safe.
            """
            def _post(fn):
                try:
                    win.after(0, fn)
                except Exception:
                    pass

            try:
                backend = _make_temp_backend(desc)
                frame = None
                try:
                    backend.open()
                    if backend.needs_streaming:
                        backend.start_capture()

                    # OpenCV tarda en estabilizar; los primeros frames son negros
                    n_warmup = self.N_WARMUP_OPCV if desc.kind == "opencv" else 0
                    for _ in range(n_warmup):
                        if self._gen != gen:
                            return
                        try:
                            backend.read_frame_bgr()
                        except Exception:
                            pass
                        time.sleep(0.05)

                    for _ in range(self.N_RETRIES):
                        if self._gen != gen:
                            return
                        try:
                            f = backend.read_frame_bgr()
                            if f is not None and f.size > 0:
                                frame = f
                                break
                        except Exception:
                            pass
                        time.sleep(0.1)

                finally:
                    try:
                        backend.close()
                    except Exception:
                        pass
                    time.sleep(0.15)   # tiempo para que el OS libere el dispositivo USB

                if self._gen != gen:
                    return

                if frame is None:
                    _post(lambda: self.info_var.set("No se pudo leer frame.")
                          if self._gen == gen else None)
                    return

                # Escalar y convertir a PIL Image (seguro en hilo de fondo)
                h, w = frame.shape[:2]
                scale = min(self.THUMB_W / w, self.THUMB_H / h)
                nw, nh = int(w * scale), int(h * scale)
                small   = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
                rgb     = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb)
                lbl_txt = "%s | %d×%d" % (desc.label, w, h)

                def _update_ui():
                    # ImageTk.PhotoImage debe crearse en el hilo principal de Tkinter
                    if self._gen != gen:
                        return
                    imgtk = ImageTk.PhotoImage(image=pil_img)
                    self.thumb_lbl.imgtk = imgtk   # ref para evitar que GC lo destruya
                    self.thumb_lbl.configure(image=imgtk, bg="#000")
                    self.info_var.set(lbl_txt)

                _post(_update_ui)

            except Exception as e:
                err = str(e)
                _post(lambda: self.info_var.set("Error: %s" % err)
                      if self._gen == gen else None)

    # ── Layout: botones al fondo primero para que nunca queden tapados ────────
    # En Tkinter pack, el orden de pack() determina el orden visual. Al empaquetar
    # bot con side="bottom" antes que panels_frame, siempre queda visible abajo.

    bot = tk.Frame(win)
    bot.pack(side="bottom", fill="x", padx=10, pady=(4, 10))

    def _do_scan():
        panel_m.cancel()
        panel_s.cancel()
        panel_m.info_var.set("Escaneando cámaras…")
        panel_s.info_var.set("Escaneando cámaras…")
        win.update()

        cams     = svc.list_cameras()
        cam_opts = [(c.label, c) for c in cams]

        sim_desc = CameraDescriptor(kind="sim_camera", id="sim", label="Simulada")
        muestra_extra = [
            (_STAGE_SIM_LABEL, sim_desc),  # ← Opción simulada para muestra
        ]
        panel_m.rebuild_menu(cam_opts, extra_top=muestra_extra)

        stage_extra = [
            (_STAGE_NONE_LABEL, None),
            (_STAGE_SIM_LABEL,  sim_desc),
        ]
        panel_s.rebuild_menu(cam_opts, extra_top=stage_extra)

    def ok():
        desc_m = panel_m.selected_desc
        if desc_m is None:
            messagebox.showerror("Selección", "Seleccioná la cámara de MUESTRA.",
                                 parent=win)
            return
        panel_m.cancel()
        panel_s.cancel()
        result["muestra"] = desc_m
        result["stage"]   = panel_s.selected_desc   # puede ser None
        win.destroy()

    def cancel():
        panel_m.cancel()
        panel_s.cancel()
        win.destroy()

    tk.Button(bot, text="🔄 Escanear", width=14,
              command=_do_scan).pack(side="left", padx=(0, 8))
    tk.Button(bot, text="✅ OK", width=14, command=ok,
              bg="#2e7d32", fg="white").pack(side="left", padx=(0, 4))
    tk.Button(bot, text="Cancelar", width=10, command=cancel).pack(side="left")

    # Paneles (después de bot para que pack side="bottom" ya esté reservado)
    panels_frame = tk.Frame(win)
    panels_frame.pack(side="top", fill="both", expand=True)

    panel_m = PreviewPanel(panels_frame, " MUESTRA  (requerida) ")
    panel_s = PreviewPanel(panels_frame, " STAGE  (opcional) ")

    panel_m.info_var.set("Iniciando escaneo…")
    panel_s.info_var.set("Iniciando escaneo…")

    # Escaneo diferido: win.after garantiza que el event loop ya está corriendo
    # cuando los hilos de preview llamen win.after(0, fn). Sin esto los callbacks
    # quedan en cola antes de wait_window y nunca se procesan.
    win.after(100, _do_scan)

    win.grab_set()
    root.wait_window(win)
    if created_root:
        try:
            root.destroy()
        except Exception:
            pass

    if result["muestra"] is None:
        raise RuntimeError("Selección de cámara cancelada.")

    svc.set_selected(result["muestra"])
    return result
