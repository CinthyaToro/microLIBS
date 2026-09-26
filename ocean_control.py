"""
Ocean Optics LIBS2500plus - Panel de Control de Espectrómetros
Autor: generado para microLIBS
Requisitos:
    pip install seabreeze matplotlib numpy libusb-package
    + Zadig para asignar driver WinUSB a cada módulo HR2000+

Uso:
    python ocean_control.py

Notas:
    - Backend pyseabreeze (Python puro, 64 bits, sin DLL del fabricante)
    - Soporta 1 a 7 módulos HR2000+ en hot-plug
    - Modos de trigger del HR2000+:
        0 = Free-running (normal)
        1 = Software trigger
        2 = Hardware Level (externo)
        3 = External Sync
        4 = Hardware Edge (para LIBS con láser)
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import csv
import os
import struct
import sys
from datetime import datetime

import numpy as np

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    MATPLOTLIB_OK = True
except ImportError:
    MATPLOTLIB_OK = False

# ── Forzar backend libusb para pyusb (necesario en Windows con Python 3.7) ──
try:
    import libusb_package
    import usb.backend.libusb1
    _lb_backend = libusb_package.get_libusb1_backend()
    if _lb_backend is not None:
        import usb.core as _usb_core
        _orig_find = _usb_core.find
        def _patched_find(*args, **kwargs):
            kwargs.setdefault('backend', _lb_backend)
            return _orig_find(*args, **kwargs)
        _usb_core.find = _patched_find
except Exception:
    pass

# ── Intentar importar seabreeze ──────────────────────────────────────────────
SEABREEZE_OK = False
_SEABREEZE_ERROR = ""
try:
    import seabreeze
    seabreeze.use("pyseabreeze")
    from seabreeze.spectrometers import Spectrometer, list_devices
    SEABREEZE_OK = True
except Exception as e:
    _SEABREEZE_ERROR = str(e)

# ── Paleta de colores por canal (A-G) ────────────────────────────────────────
CHANNEL_COLORS = ["#00BFFF", "#7CFC00", "#FF8C00", "#FF1493",
                  "#BF5FFF", "#FFD700", "#00FA9A"]
CHANNEL_NAMES  = list("ABCDEFG")

# Opción "todos los módulos" del selector de registros FPGA. Las operaciones de
# lectura la aceptan; la escritura (0x6A) exige un módulo concreto.
TARGET_ALL = "Todos (solo lectura)"

# ─────────────────────────────────────────────────────────────────────────────
# Clase que representa un módulo HR2000+
# ─────────────────────────────────────────────────────────────────────────────
class SpecModule:
    def __init__(self, device, channel_letter, color):
        self.device         = device
        self.channel        = channel_letter
        self.color          = color
        try:
            self.serial     = device.serial_number
        except Exception as e:
            # Módulo con driver/USB en mal estado: no tirar abajo el escaneo
            # de los demás módulos por esto. Se reporta como error más abajo.
            self.serial     = "??? (%s)" % e
        self.spec           = None          # Spectrometer abierto
        self.wavelengths    = None
        self.intensities    = None
        self.error          = None
        self.acq_failed     = False         # última adquisición falló (para el log)
        self.integration_us = 10000         # 10 ms por defecto
        self.trigger_mode   = 0
        self.visible        = True

    def open(self):
        try:
            self.spec = Spectrometer(self.device)
            self.spec.integration_time_micros(self.integration_us)
            self.spec.trigger_mode(0)
            self.wavelengths = self.spec.wavelengths()
            self.error = None
            return True
        except Exception as e:
            self.error = str(e)
            return False

    def close(self):
        try:
            if self.spec:
                self.spec.trigger_mode(0)
                self.spec.close()
                self.spec = None
        except Exception:
            pass

    def acquire(self):
        if not self.spec:
            return False
        try:
            self.intensities = self.spec.intensities()
            self.error = None
            return True
        except Exception as e:
            self.error = str(e)
            return False

    def set_integration(self, us):
        self.integration_us = us
        if self.spec:
            try:
                self.spec.integration_time_micros(us)
            except Exception as e:
                self.error = str(e)

    def set_trigger(self, mode):
        self.trigger_mode = mode
        if self.spec:
            try:
                self.spec.trigger_mode(mode)
            except Exception as e:
                self.error = str(e)

    # ─────────────────────────────────────────────────────────────────────────
    # DELAY DE ADQUISICIÓN  (trigger TTL → inicio de integración)
    # ─────────────────────────────────────────────────────────────────────────
    # Dos caminos, en orden de preferencia:
    #
    #   1. API de seabreeze — feature "acquisition_delay".
    #      Limpia y portable. En pyseabreeze la feature está DECLARADA para
    #      varios modelos pero puede no estar IMPLEMENTADA para el HR2000+
    #      (levanta NotImplementedError). Siempre probar esto primero.
    #
    #   2. Acceso crudo al bus USB — feature "raw_usb_bus_access", usando los
    #      opcodes del protocolo OOI:
    #          0x6B  Read  FPGA Register Information
    #          0x6A  Write FPGA Register Information
    #      Esto es ingeniería inversa sobre el firmware. Por defecto se usa
    #      SOLO EN LECTURA. La escritura queda detrás de un candado explícito
    #      en la UI y siempre hace read-back de verificación.
    #
    # ⚠ Escribir un registro FPGA equivocado puede dejar el módulo en un estado
    #   raro hasta el próximo ciclo de alimentación. No es destructivo, pero
    #   puede costar una sesión de laboratorio. Mapear antes, escribir después.

    OOI_READ_REGISTER  = 0x6B
    OOI_WRITE_REGISTER = 0x6A
    REG_FPGA_FIRMWARE  = 0x04   # sonda segura de solo lectura (versión firmware)

    def _feature(self, name):
        """Primera instancia de una feature de seabreeze, o None."""
        if not self.spec:
            return None
        try:
            feats = self.spec.features.get(name, [])
            return feats[0] if feats else None
        except Exception:
            return None

    def feature_names(self):
        """
        Lista de features REALMENTE soportadas por este módulo (diagnóstico).
        self.spec.features es un dict {nombre_clase: [instancias]} que incluye
        como clave TODAS las clases de feature que conoce pyseabreeze, aunque
        el módulo no las tenga (lista vacía). Por eso se filtran las vacías:
        sin este filtro, un HR2000+ (USB, sin red) aparecía "soportando"
        ethernet_configuration, wifi_configuration, dhcp_server, etc.
        """
        if not self.spec:
            return []
        try:
            return sorted(name for name, insts in self.spec.features.items()
                          if insts)
        except Exception:
            return []

    def delay_capabilities(self) -> dict:
        """
        Reporta qué caminos de delay soporta ESTE módulo.
        No escribe nada en el hardware: es seguro llamarlo siempre.
        """
        caps = {
            "serial": self.serial, "channel": self.channel,
            "feature": False, "raw_usb": False,
            "min_us": 0, "max_us": 0, "inc_us": 1,
            "detail": "", "features": self.feature_names(),
        }
        f = self._feature("acquisition_delay")
        if f is None:
            caps["detail"] = "sin feature 'acquisition_delay'"
        else:
            try:
                caps["min_us"] = int(f.get_minimum_delay_microseconds())
                caps["max_us"] = int(f.get_maximum_delay_microseconds())
                caps["inc_us"] = int(f.get_delay_increment_microseconds())
                caps["feature"] = True
                caps["detail"] = "feature operativa"
            except NotImplementedError:
                caps["detail"] = "feature declarada pero NO implementada para este modelo"
            except Exception as e:
                caps["detail"] = "feature falló: %s" % e
        caps["raw_usb"] = self._feature("raw_usb_bus_access") is not None
        return caps

    def get_delay_us(self):
        """Delay actual en µs vía API de seabreeze, o None si no soportado."""
        f = self._feature("acquisition_delay")
        if f is None:
            return None
        try:
            return int(f.get_delay_microseconds())
        except Exception:
            return None

    def set_delay_us(self, us: int) -> None:
        """Fija el delay vía API de seabreeze. Lanza si no está soportado."""
        f = self._feature("acquisition_delay")
        if f is None:
            raise RuntimeError("%s: sin feature 'acquisition_delay'" % self.serial)
        f.set_delay_microseconds(int(us))

    # ── Acceso crudo (Etapa 3: ingeniería inversa del registro de delay) ─────

    def raw_read_register(self, reg: int, n_bytes: int = 3) -> bytes:
        """
        Envía 0x6B <reg> y lee n_bytes de respuesta. SOLO LECTURA.
        Devuelve los bytes crudos: la interpretación queda al analista.
        """
        f = self._feature("raw_usb_bus_access")
        if f is None:
            raise RuntimeError("%s: sin feature 'raw_usb_bus_access'" % self.serial)
        f.raw_usb_write(bytes([self.OOI_READ_REGISTER, reg & 0xFF]), "primary_out")
        return bytes(f.raw_usb_read("primary_in", n_bytes))

    def raw_write_register(self, reg: int, value: int) -> None:
        """
        Envía 0x6A <reg> <valor u16 little-endian>. ESCRITURA REAL.
        El llamador es responsable de hacer read-back y de saber qué registro toca.
        """
        f = self._feature("raw_usb_bus_access")
        if f is None:
            raise RuntimeError("%s: sin feature 'raw_usb_bus_access'" % self.serial)
        payload = struct.pack("<BBH", self.OOI_WRITE_REGISTER,
                              reg & 0xFF, value & 0xFFFF)
        f.raw_usb_write(payload, "primary_out")

    def raw_map_registers(self, first: int = 0x00, last: int = 0x3F,
                          n_bytes: int = 3) -> dict:
        """
        Lee un rango de registros FPGA. SOLO LECTURA — no modifica nada.
        Devuelve {registro: hex_string | "ERR:..."}.

        Uso previsto: sacar una foto del mapa de registros, cambiar el delay
        con otra herramienta (o con la API si funciona), volver a mapear y
        comparar. El registro que cambió es el registro de delay.
        """
        out = {}
        for reg in range(first, last + 1):
            try:
                raw = self.raw_read_register(reg, n_bytes)
                out[reg] = raw.hex()
            except Exception as e:
                out[reg] = "ERR:%s" % e
        return out

    @property
    def range_label(self):
        if self.wavelengths is not None:
            return f"{self.wavelengths[0]:.0f}–{self.wavelengths[-1]:.0f} nm"
        return "desconocido"

# ─────────────────────────────────────────────────────────────────────────────
# Ventana principal
# ─────────────────────────────────────────────────────────────────────────────
class OceanControlApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ocean Optics LIBS2500plus — Control de Espectrómetros")
        self.configure(bg="#0D1117")
        self.resizable(True, True)

        # Tamaño inicial acotado a la pantalla real. Con 1280x780 fijos, en
        # notebooks con pantalla chica (p.ej. 1366x768 o menos) la parte de
        # abajo de la ventana (Log, botones Iniciar/Detener) quedaba fuera
        # del área visible, tapada por la barra de tareas.
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w = min(1280, screen_w - 40)
        win_h = min(780, screen_h - 80)
        self.geometry(f"{win_w}x{win_h}+20+20")
        self.minsize(900, 500)

        self.modules: list = []
        self._acquiring = False
        self._acq_thread = None
        self._acq_interval_ms = 200

        self._build_ui()
        self._check_deps()

    # ── Construcción de la UI ─────────────────────────────────────────────
    def _build_ui(self):
        # Fuente principal
        self.option_add("*Font", "Consolas 10")

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TLabel",     background="#0D1117", foreground="#E6EDF3")
        style.configure("TFrame",     background="#0D1117")
        style.configure("TLabelframe",background="#161B22", foreground="#58A6FF",
                        bordercolor="#30363D")
        style.configure("TLabelframe.Label", background="#161B22",
                        foreground="#58A6FF", font="Consolas 10 bold")
        style.configure("TButton",    background="#21262D", foreground="#E6EDF3",
                        bordercolor="#30363D", focuscolor="#0D1117")
        style.map("TButton",
                  background=[("active", "#30363D"), ("pressed", "#388BFD")])
        style.configure("TCombobox",  fieldbackground="#21262D",
                        background="#21262D", foreground="#E6EDF3",
                        selectbackground="#388BFD")
        style.configure("TEntry",     fieldbackground="#21262D",
                        foreground="#E6EDF3", insertcolor="#E6EDF3")
        style.configure("TCheckbutton", background="#161B22",
                        foreground="#E6EDF3")
        style.configure("TScale",     background="#161B22", troughcolor="#21262D",
                        sliderthickness=14)

        # ── Barra superior ──────────────────────────────────────────────
        top = tk.Frame(self, bg="#161B22", height=50)
        top.pack(fill="x", side="top")
        tk.Label(top, text="◈  OCEAN OPTICS  LIBS2500plus",
                 bg="#161B22", fg="#58A6FF",
                 font="Consolas 14 bold").pack(side="left", padx=16, pady=8)

        self._lbl_status = tk.Label(top, text="●  Sin conectar",
                                    bg="#161B22", fg="#F85149",
                                    font="Consolas 10 bold")
        self._lbl_status.pack(side="right", padx=16)

        # ── Panel izquierdo (controles), con scroll ──────────────────────
        # Con varios módulos detectados (cada uno agrega una fila a
        # "Detección de Módulos") el contenido puede superar el alto de la
        # ventana. Sin scroll, las secciones de más abajo (Adquisición
        # Continua, Guardar Espectro, Log) quedaban directamente ocultas,
        # fuera del área visible, sin ningún error ni aviso.
        left_container = tk.Frame(self, bg="#0D1117", width=300)
        left_container.pack(side="left", fill="y", padx=8, pady=8)
        left_container.pack_propagate(False)

        left_canvas = tk.Canvas(left_container, bg="#0D1117",
                                highlightthickness=0)
        left_scrollbar = ttk.Scrollbar(left_container, orient="vertical",
                                       command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_scrollbar.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)

        left = tk.Frame(left_canvas, bg="#0D1117")
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_left_configure(event):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        left.bind("<Configure>", _on_left_configure)

        def _on_canvas_configure(event):
            left_canvas.itemconfigure(left_window, width=event.width)
        left_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            left_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _bind_mousewheel(_event):
            left_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_mousewheel(_event):
            left_canvas.unbind_all("<MouseWheel>")
        left_canvas.bind("<Enter>", _bind_mousewheel)
        left_canvas.bind("<Leave>", _unbind_mousewheel)

        # — Detección —
        lf_det = ttk.LabelFrame(left, text="  Detección de Módulos")
        lf_det.pack(fill="x", pady=(0, 8))

        tk.Button(lf_det, text="⟳  Escanear USB",
                  bg="#238636", fg="white", font="Consolas 10 bold",
                  relief="flat", pady=6, cursor="hand2",
                  command=self._scan_devices).pack(fill="x", padx=8, pady=8)

        self._modules_frame = tk.Frame(lf_det, bg="#161B22")
        self._modules_frame.pack(fill="x", padx=4, pady=(0, 6))

        # — Tiempo de integración —
        lf_int = ttk.LabelFrame(left, text="  Integración (µs)")
        lf_int.pack(fill="x", pady=(0, 8))

        int_row = tk.Frame(lf_int, bg="#161B22")
        int_row.pack(fill="x", padx=8, pady=6)
        self._int_var = tk.StringVar(value="10000")
        tk.Entry(int_row, textvariable=self._int_var,
                 bg="#21262D", fg="#E6EDF3",
                 insertbackground="#E6EDF3",
                 width=10, font="Consolas 11").pack(side="left")
        tk.Button(int_row, text="Aplicar",
                  bg="#21262D", fg="#58A6FF",
                  relief="flat", cursor="hand2",
                  command=self._apply_integration).pack(side="left", padx=6)

        presets = [("2100 µs", 2100), ("10 ms", 10000),
                   ("50 ms", 50000), ("100 ms", 100000)]
        prow = tk.Frame(lf_int, bg="#161B22")
        prow.pack(fill="x", padx=8, pady=(0, 6))
        for label, val in presets:
            tk.Button(prow, text=label, bg="#21262D", fg="#8B949E",
                      relief="flat", cursor="hand2",
                      command=lambda v=val: self._set_integration_preset(v)
                      ).pack(side="left", padx=2)

        # — Modo trigger —
        lf_trg = ttk.LabelFrame(left, text="  Modo Trigger")
        lf_trg.pack(fill="x", pady=(0, 8))
        self._trigger_var = tk.IntVar(value=0)
        trg_options = [
            (0, "0 – Free-running"),
            (1, "1 – Software"),
            (2, "2 – HW Level"),
            (3, "3 – Ext. Sync"),
            (4, "4 – HW Edge (LIBS)"),
        ]
        for val, lbl in trg_options:
            tk.Radiobutton(lf_trg, text=lbl, variable=self._trigger_var,
                           value=val, bg="#161B22", fg="#E6EDF3",
                           selectcolor="#21262D", activebackground="#161B22",
                           activeforeground="#58A6FF",
                           command=self._apply_trigger).pack(
                               anchor="w", padx=12, pady=1)

        # — Delay de adquisición (gate delay LIBS) —
        lf_dly = ttk.LabelFrame(left, text="  Delay de adquisición (µs)")
        lf_dly.pack(fill="x", pady=(0, 8))

        tk.Button(lf_dly, text="🔎  Detectar soporte de delay",
                  bg="#21262D", fg="#58A6FF", relief="flat", cursor="hand2",
                  command=self._delay_detect).pack(fill="x", padx=8, pady=(8, 4))

        dly_row = tk.Frame(lf_dly, bg="#161B22")
        dly_row.pack(fill="x", padx=8, pady=(0, 6))
        self._delay_var = tk.StringVar(value="0")
        tk.Entry(dly_row, textvariable=self._delay_var,
                 bg="#21262D", fg="#E6EDF3", insertbackground="#E6EDF3",
                 width=10, font="Consolas 11").pack(side="left")
        tk.Button(dly_row, text="Leer", bg="#21262D", fg="#8B949E",
                  relief="flat", cursor="hand2",
                  command=self._delay_read).pack(side="left", padx=4)
        tk.Button(dly_row, text="Aplicar", bg="#21262D", fg="#58A6FF",
                  relief="flat", cursor="hand2",
                  command=self._delay_apply).pack(side="left", padx=2)

        # — Etapa 3: sonda de registros FPGA (ingeniería inversa) —
        lf_raw = ttk.LabelFrame(left, text="  Registros FPGA  (avanzado)")
        lf_raw.pack(fill="x", pady=(0, 8))

        tk.Label(lf_raw,
                 text="0x6B = leer · 0x6A = escribir\n"
                      "La escritura está bloqueada por defecto\n"
                      "y sólo actúa sobre UN módulo.",
                 bg="#161B22", fg="#D29922", font="Consolas 8",
                 justify="left").pack(anchor="w", padx=8, pady=(6, 2))

        raw_target = tk.Frame(lf_raw, bg="#161B22")
        raw_target.pack(fill="x", padx=8, pady=2)
        tk.Label(raw_target, text="módulo", bg="#161B22", fg="#8B949E",
                 font="Consolas 9").pack(side="left")
        self._raw_target_var = tk.StringVar(value=TARGET_ALL)
        self._raw_target_combo = ttk.Combobox(
            raw_target, textvariable=self._raw_target_var,
            state="readonly", values=[TARGET_ALL],
            width=20, font="Consolas 9")
        self._raw_target_combo.pack(side="left", padx=4)

        raw_row1 = tk.Frame(lf_raw, bg="#161B22")
        raw_row1.pack(fill="x", padx=8, pady=2)
        tk.Label(raw_row1, text="reg", bg="#161B22", fg="#8B949E",
                 font="Consolas 9").pack(side="left")
        self._raw_reg_var = tk.StringVar(value="0x04")
        tk.Entry(raw_row1, textvariable=self._raw_reg_var, width=6,
                 bg="#21262D", fg="#E6EDF3", insertbackground="#E6EDF3",
                 font="Consolas 10").pack(side="left", padx=(4, 8))
        tk.Label(raw_row1, text="bytes", bg="#161B22", fg="#8B949E",
                 font="Consolas 9").pack(side="left")
        self._raw_nbytes_var = tk.StringVar(value="3")
        tk.Entry(raw_row1, textvariable=self._raw_nbytes_var, width=4,
                 bg="#21262D", fg="#E6EDF3", insertbackground="#E6EDF3",
                 font="Consolas 10").pack(side="left", padx=4)
        tk.Button(raw_row1, text="Leer", bg="#238636", fg="white",
                  relief="flat", cursor="hand2",
                  command=self._raw_read).pack(side="left", padx=4)

        raw_row2 = tk.Frame(lf_raw, bg="#161B22")
        raw_row2.pack(fill="x", padx=8, pady=2)
        tk.Label(raw_row2, text="val", bg="#161B22", fg="#8B949E",
                 font="Consolas 9").pack(side="left")
        self._raw_val_var = tk.StringVar(value="0")
        tk.Entry(raw_row2, textvariable=self._raw_val_var, width=10,
                 bg="#21262D", fg="#E6EDF3", insertbackground="#E6EDF3",
                 font="Consolas 10").pack(side="left", padx=(4, 8))
        self._raw_unlock_var = tk.BooleanVar(value=False)
        tk.Checkbutton(raw_row2, text="habilitar escritura",
                       variable=self._raw_unlock_var,
                       bg="#161B22", fg="#F85149", selectcolor="#21262D",
                       activebackground="#161B22", font="Consolas 8",
                       command=self._raw_toggle_write).pack(side="left")

        self._btn_raw_write = tk.Button(lf_raw, text="✎  Escribir registro (0x6A)",
                                        bg="#DA3633", fg="white", relief="flat",
                                        cursor="hand2", state="disabled",
                                        command=self._raw_write)
        self._btn_raw_write.pack(fill="x", padx=8, pady=2)

        # Rango del mapeo. El espacio direccionable es 0x00–0xFF (la dirección
        # viaja en un byte); el default 0x00–0x3F es sólo el primer cuarto.
        raw_range = tk.Frame(lf_raw, bg="#161B22")
        raw_range.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(raw_range, text="mapa  desde", bg="#161B22", fg="#8B949E",
                 font="Consolas 9").pack(side="left")
        self._raw_first_var = tk.StringVar(value="0x00")
        tk.Entry(raw_range, textvariable=self._raw_first_var, width=6,
                 bg="#21262D", fg="#E6EDF3", insertbackground="#E6EDF3",
                 font="Consolas 10").pack(side="left", padx=(4, 8))
        tk.Label(raw_range, text="hasta", bg="#161B22", fg="#8B949E",
                 font="Consolas 9").pack(side="left")
        self._raw_last_var = tk.StringVar(value="0x3F")
        tk.Entry(raw_range, textvariable=self._raw_last_var, width=6,
                 bg="#21262D", fg="#E6EDF3", insertbackground="#E6EDF3",
                 font="Consolas 10").pack(side="left", padx=4)

        tk.Button(lf_raw, text="🗺  Mapear rango (solo lectura)",
                  bg="#21262D", fg="#E6EDF3", relief="flat", cursor="hand2",
                  command=self._raw_map).pack(fill="x", padx=8, pady=(2, 8))

        # — Adquisición continua —
        lf_acq = ttk.LabelFrame(left, text="  Adquisición Continua")
        lf_acq.pack(fill="x", pady=(0, 8))
        acq_row = tk.Frame(lf_acq, bg="#161B22")
        acq_row.pack(fill="x", padx=8, pady=6)
        self._btn_start = tk.Button(acq_row, text="▶  Iniciar",
                                    bg="#238636", fg="white",
                                    relief="flat", cursor="hand2",
                                    font="Consolas 10 bold",
                                    command=self._start_acquisition)
        self._btn_start.pack(side="left", padx=(0, 4))
        self._btn_stop = tk.Button(acq_row, text="■  Detener",
                                   bg="#DA3633", fg="white",
                                   relief="flat", cursor="hand2",
                                   font="Consolas 10 bold",
                                   state="disabled",
                                   command=self._stop_acquisition)
        self._btn_stop.pack(side="left")

        tk.Button(lf_acq, text="▸  Un Disparo",
                  bg="#1F6FEB", fg="white", relief="flat",
                  cursor="hand2", font="Consolas 10",
                  command=self._single_shot).pack(fill="x", padx=8, pady=(0, 8))

        # — Guardar datos —
        lf_save = ttk.LabelFrame(left, text="  Guardar Espectro")
        lf_save.pack(fill="x", pady=(0, 8))
        tk.Button(lf_save, text="💾  Exportar CSV",
                  bg="#21262D", fg="#E6EDF3", relief="flat",
                  cursor="hand2",
                  command=self._export_csv).pack(fill="x", padx=8, pady=8)

        # — Log —
        lf_log = ttk.LabelFrame(left, text="  Log")
        lf_log.pack(fill="both", expand=True, pady=(0, 0))
        self._log = tk.Text(lf_log, bg="#010409", fg="#8B949E",
                            insertbackground="#E6EDF3",
                            font="Consolas 9", height=10, wrap="word",
                            state="disabled", relief="flat")
        self._log.pack(fill="both", expand=True, padx=4, pady=4)

        # ── Panel derecho (gráfico) ─────────────────────────────────────
        right = tk.Frame(self, bg="#0D1117")
        right.pack(side="right", fill="both", expand=True, padx=(0, 8), pady=8)

        if MATPLOTLIB_OK:
            self._fig = Figure(figsize=(8, 5),
                               facecolor="#0D1117", edgecolor="#0D1117")
            self._ax  = self._fig.add_subplot(111)
            self._style_ax()

            self._canvas = FigureCanvasTkAgg(self._fig, master=right)
            self._canvas.get_tk_widget().pack(fill="both", expand=True)

            toolbar_frame = tk.Frame(right, bg="#161B22")
            toolbar_frame.pack(fill="x")
            NavigationToolbar2Tk(self._canvas, toolbar_frame)
        else:
            tk.Label(right,
                     text="⚠  matplotlib no instalado\npip install matplotlib",
                     bg="#0D1117", fg="#F85149",
                     font="Consolas 12").pack(expand=True)

        # ── Barra de estado inferior ────────────────────────────────────
        bot = tk.Frame(self, bg="#161B22", height=24)
        bot.pack(fill="x", side="bottom")
        self._lbl_info = tk.Label(bot, text="Listo.",
                                  bg="#161B22", fg="#8B949E",
                                  font="Consolas 9")
        self._lbl_info.pack(side="left", padx=10)
        self._lbl_fps = tk.Label(bot, text="",
                                 bg="#161B22", fg="#3FB950",
                                 font="Consolas 9 bold")
        self._lbl_fps.pack(side="right", padx=10)

    # ── Estilos del gráfico ───────────────────────────────────────────────
    def _style_ax(self):
        ax = self._ax
        ax.set_facecolor("#010409")
        ax.tick_params(colors="#8B949E", labelsize=8)
        ax.spines["bottom"].set_color("#30363D")
        ax.spines["left"].set_color("#30363D")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.set_xlabel("Longitud de onda (nm)", color="#8B949E", fontsize=9)
        ax.set_ylabel("Intensidad (u.a.)", color="#8B949E", fontsize=9)
        ax.set_title("Espectro – sin datos", color="#58A6FF", fontsize=10)
        ax.grid(True, color="#21262D", linestyle="--", linewidth=0.5)
        self._fig.tight_layout(pad=1.5)

    # ── Verificación de dependencias ─────────────────────────────────────
    def _check_deps(self):
        if not MATPLOTLIB_OK:
            self._log_msg("⚠  matplotlib no encontrado — pip install matplotlib",
                          "warn")
        if not SEABREEZE_OK:
            self._log_msg("⚠  seabreeze no encontrado — pip install seabreeze",
                          "warn")
            self._log_msg(f"   Error: {_SEABREEZE_ERROR}", "warn")
            self._lbl_status.configure(
                text="●  seabreeze no instalado", fg="#F85149")
        else:
            self._log_msg("✓  seabreeze (pyseabreeze) cargado correctamente",
                          "ok")
            self._log_msg("   Hacé clic en 'Escanear USB' para detectar módulos.")

    # ── Log ───────────────────────────────────────────────────────────────
    def _log_msg(self, msg, level="info"):
        colors = {"info": "#8B949E", "ok": "#3FB950",
                  "warn": "#D29922", "err": "#F85149"}
        color = colors.get(level, "#8B949E")
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.configure(state="normal")
        self._log.insert("end", f"[{ts}] {msg}\n", level)
        self._log.tag_configure(level, foreground=color)
        self._log.see("end")
        self._log.configure(state="disabled")

    # ── Escanear dispositivos ─────────────────────────────────────────────
    def _scan_devices(self):
        if not SEABREEZE_OK:
            messagebox.showerror("Error",
                "seabreeze no está instalado.\n\npip install seabreeze")
            return

        self._stop_acquisition()
        for m in self.modules:
            m.close()
        self.modules.clear()

        # Limpiar widgets de módulos anteriores
        for w in self._modules_frame.winfo_children():
            w.destroy()

        self._log_msg("Escaneando dispositivos USB…")
        try:
            devices = list_devices()
        except Exception as e:
            self._log_msg(f"✗ Error al listar dispositivos: {e}", "err")
            self._lbl_status.configure(text="●  Error de escaneo", fg="#F85149")
            return

        if not devices:
            self._log_msg("✗ Ningún módulo detectado. Verificá:", "warn")
            self._log_msg("   1. Que el rack esté enchufado y encendido", "warn")
            self._log_msg("   2. Que Zadig asignó driver WinUSB a cada HR2000+",
                          "warn")
            self._lbl_status.configure(
                text="●  Sin módulos", fg="#D29922")
            return

        # Ordenar por número de serie (= orden de canales A→G).
        # Si un módulo tiene el driver/USB en mal estado, leer su serial
        # puede lanzar una excepción: no dejar que eso tumbe el sorted()
        # y con él la detección de TODOS los módulos.
        def _safe_serial(d):
            try:
                return d.serial_number
            except Exception:
                return "￿"  # empuja los que fallan al final, sin romper el orden
        devices_sorted = sorted(devices, key=_safe_serial)

        for i, dev in enumerate(devices_sorted):
            letter = CHANNEL_NAMES[i] if i < len(CHANNEL_NAMES) else str(i)
            color  = CHANNEL_COLORS[i % len(CHANNEL_COLORS)]
            try:
                m = SpecModule(dev, letter, color)
                ok = m.open()
            except Exception as e:
                # Un módulo roto no debe impedir ver los otros tres.
                self._log_msg(
                    f"✗ Canal {letter}: fallo inesperado al inicializar — {e}",
                    "err")
                continue
            self.modules.append(m)

            self._build_module_widget(m, ok)

            if ok:
                self._log_msg(
                    f"✓ Canal {letter}: {m.serial}  [{m.range_label}]", "ok")
            else:
                self._log_msg(
                    f"✗ Canal {letter}: {m.serial}  — {m.error}", "err")

        n = len(self.modules)
        n_ok = sum(1 for m in self.modules if m.spec is not None)
        self._lbl_status.configure(
            text=f"●  {n_ok}/{n} módulos OK",
            fg="#3FB950" if n_ok == n else "#D29922")
        self._lbl_info.configure(
            text=f"{n} módulo(s) detectado(s) — {n_ok} operativos")
        self._refresh_raw_targets()

    # ── Widget de módulo individual ───────────────────────────────────────
    def _build_module_widget(self, m, ok):
        frame = tk.Frame(self._modules_frame, bg="#21262D",
                         highlightbackground=m.color if ok else "#F85149",
                         highlightthickness=1)
        frame.pack(fill="x", pady=2, padx=2)

        # Indicador de color de canal
        tk.Label(frame, text=f"  {m.channel}  ",
                 bg=m.color if ok else "#F85149",
                 fg="#0D1117", font="Consolas 10 bold",
                 width=3).pack(side="left")

        info = tk.Frame(frame, bg="#21262D")
        info.pack(side="left", fill="x", expand=True, padx=6)
        status = "✓" if ok else "✗"
        col    = "#3FB950" if ok else "#F85149"
        tk.Label(info, text=f"{status} {m.serial}",
                 bg="#21262D", fg=col,
                 font="Consolas 9 bold").pack(anchor="w")
        tk.Label(info, text=m.range_label if ok else m.error,
                 bg="#21262D", fg="#8B949E",
                 font="Consolas 8").pack(anchor="w")

        # Checkbox visible/oculto en gráfico
        m._vis_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="vis",
                       variable=m._vis_var,
                       bg="#21262D", fg="#8B949E",
                       selectcolor="#0D1117",
                       activebackground="#21262D",
                       command=self._update_plot).pack(side="right", padx=4)

    # ── Integración ───────────────────────────────────────────────────────
    def _apply_integration(self):
        try:
            us = int(self._int_var.get())
            if us < 2100:
                messagebox.showwarning("Advertencia",
                    "El mínimo para HR2000+ es 2100 µs.\nSe usará 2100 µs.")
                us = 2100
                self._int_var.set("2100")
        except ValueError:
            messagebox.showerror("Error", "Valor inválido de integración.")
            return
        for m in self.modules:
            m.set_integration(us)
        self._log_msg(f"Integración → {us} µs ({us/1000:.1f} ms)")

    def _set_integration_preset(self, val):
        self._int_var.set(str(val))
        self._apply_integration()

    # ── Trigger ────────────────────────────────────────────────────────────
    def _apply_trigger(self):
        mode = self._trigger_var.get()
        for m in self.modules:
            m.set_trigger(mode)
        labels = {0: "Free-running", 1: "Software", 2: "HW Level",
                  3: "Ext. Sync", 4: "HW Edge (LIBS)"}
        self._log_msg(f"Trigger → modo {mode}: {labels.get(mode, '')}")
        if mode == 4:
            self._log_msg(
                "  ⚑ Modo LIBS: el espectrómetro esperará TTL del láser.",
                "warn")

    # ── Delay de adquisición ─────────────────────────────────────────────

    def _ok_mods(self):
        return [m for m in self.modules if m.spec is not None]

    @staticmethod
    def _mod_label(m):
        return "%s — %s" % (m.channel, m.serial)

    def _refresh_raw_targets(self):
        """Repuebla el selector de módulo tras un escaneo, conservando la
        selección previa si ese módulo sigue presente."""
        labels = [self._mod_label(m) for m in self._ok_mods()]
        self._raw_target_combo.configure(values=[TARGET_ALL] + labels)
        if self._raw_target_var.get() not in labels:
            self._raw_target_var.set(TARGET_ALL)

    def _raw_targets(self):
        """Módulos alcanzados por las operaciones de registro FPGA."""
        sel = self._raw_target_var.get()
        mods = self._ok_mods()
        if sel == TARGET_ALL:
            return mods
        return [m for m in mods if self._mod_label(m) == sel]

    def _guard_idle(self) -> bool:
        """Impide tocar registros mientras hay adquisición continua corriendo."""
        if self._acquiring:
            messagebox.showwarning(
                "Adquisición en curso",
                "Detené la adquisición continua antes de leer o escribir registros.\n"
                "El HR2000+ tiene un solo canal de control por USB.")
            return False
        if not self._ok_mods():
            messagebox.showinfo("Sin módulos", "No hay módulos operativos.")
            return False
        return True

    def _delay_detect(self):
        """Reporta, módulo por módulo, qué camino de delay está disponible."""
        if not self._guard_idle():
            return
        self._log_msg("── Detección de soporte de delay ─────────────", "info")
        for m in self._ok_mods():
            caps = m.delay_capabilities()
            if caps["feature"]:
                self._log_msg(
                    "✓ Canal %s (%s): API seabreeze OK — rango %d–%d µs, paso %d"
                    % (m.channel, m.serial, caps["min_us"],
                       caps["max_us"], caps["inc_us"]), "ok")
            else:
                self._log_msg("✗ Canal %s (%s): %s"
                              % (m.channel, m.serial, caps["detail"]), "warn")
            self._log_msg("   raw_usb_bus_access: %s"
                          % ("disponible" if caps["raw_usb"] else "NO disponible"),
                          "ok" if caps["raw_usb"] else "err")
            self._log_msg("   features: %s" % ", ".join(caps["features"]), "info")
        self._log_msg("──────────────────────────────────────────────", "info")

    def _delay_read(self):
        if not self._guard_idle():
            return
        vals = []
        for m in self._ok_mods():
            v = m.get_delay_us()
            vals.append(v)
            self._log_msg("Canal %s (%s): delay = %s"
                          % (m.channel, m.serial,
                             "%d µs" % v if v is not None else "no soportado"),
                          "ok" if v is not None else "warn")
        reales = [v for v in vals if v is not None]
        if reales:
            self._delay_var.set(str(reales[0]))

    def _delay_apply(self):
        if not self._guard_idle():
            return
        try:
            us = int(float(self._delay_var.get()))
        except ValueError:
            messagebox.showerror("Delay", "Valor de delay inválido.")
            return
        if us < 0:
            messagebox.showerror("Delay", "El delay no puede ser negativo.")
            return
        for m in self._ok_mods():
            try:
                m.set_delay_us(us)
                back = m.get_delay_us()
                self._log_msg("Canal %s: delay → %d µs (read-back: %s)"
                              % (m.channel, us,
                                 "%d" % back if back is not None else "?"), "ok")
            except NotImplementedError:
                self._log_msg("Canal %s: la API no implementa delay en este modelo"
                              % m.channel, "warn")
            except Exception as e:
                self._log_msg("Canal %s: error al fijar delay: %s"
                              % (m.channel, e), "err")

    # ── Registros FPGA crudos (Etapa 3) ──────────────────────────────────

    @staticmethod
    def _parse_int(text: str) -> int:
        """Acepta '0x2C', '44' o '0b101100'."""
        return int(str(text).strip(), 0)

    def _raw_toggle_write(self):
        if self._raw_unlock_var.get():
            ok = messagebox.askyesno(
                "Habilitar escritura de registros",
                "Vas a habilitar la ESCRITURA directa de registros FPGA (0x6A).\n\n"
                "Escribir un registro equivocado puede dejar el módulo en un estado "
                "inconsistente hasta el próximo apagado del rack.\n\n"
                "Recomendación: mapeá primero (solo lectura) y anotá los valores "
                "originales.\n\n¿Continuar?")
            if not ok:
                self._raw_unlock_var.set(False)
        self._btn_raw_write.configure(
            state="normal" if self._raw_unlock_var.get() else "disabled")

    def _raw_read(self):
        if not self._guard_idle():
            return
        try:
            reg = self._parse_int(self._raw_reg_var.get())
            n   = max(1, min(64, int(self._raw_nbytes_var.get())))
        except ValueError:
            messagebox.showerror("Registro", "Registro o cantidad de bytes inválidos.")
            return
        targets = self._raw_targets()
        if not targets:
            messagebox.showinfo("Sin módulos",
                                "El módulo seleccionado ya no está disponible.\n"
                                "Volvé a escanear el bus USB.")
            return
        self._log_msg("── Lectura 0x6B reg=0x%02X (%d bytes) ──" % (reg, n), "info")
        for m in targets:
            try:
                raw = m.raw_read_register(reg, n)
                extra = ""
                if len(raw) >= 2:
                    le = int.from_bytes(raw[-2:], "little")
                    be = int.from_bytes(raw[-2:], "big")
                    extra = "  (u16 LE=%d / BE=%d)" % (le, be)
                self._log_msg("Canal %s (%s): %s%s"
                              % (m.channel, m.serial, raw.hex(" "), extra), "ok")
            except Exception as e:
                self._log_msg("Canal %s: %s" % (m.channel, e), "err")

    def _raw_write(self):
        if not self._raw_unlock_var.get():
            return
        if not self._guard_idle():
            return
        try:
            reg = self._parse_int(self._raw_reg_var.get())
            val = self._parse_int(self._raw_val_var.get())
        except ValueError:
            messagebox.showerror("Registro", "Registro o valor inválidos.")
            return
        if self._raw_target_var.get() == TARGET_ALL:
            messagebox.showerror(
                "Escritura",
                "Seleccioná UN módulo concreto en el desplegable antes de escribir.\n\n"
                "La escritura de registros FPGA nunca se aplica a todos los "
                "módulos a la vez.")
            return
        targets = self._raw_targets()
        if not targets:
            messagebox.showerror("Escritura",
                                 "El módulo seleccionado ya no está disponible.\n"
                                 "Volvé a escanear el bus USB.")
            return
        m = targets[0]

        if not messagebox.askyesno(
                "Confirmar escritura",
                "Escribir reg 0x%02X = %d (0x%04X)\n"
                "en el canal %s (%s).\n\n"
                "¿Confirmás?" % (reg, val, val & 0xFFFF, m.channel, m.serial)):
            return

        try:
            antes = m.raw_read_register(reg, 3).hex(" ")
        except Exception as e:
            antes = "ERR:%s" % e
        try:
            m.raw_write_register(reg, val)
        except Exception as e:
            self._log_msg("Canal %s: fallo al escribir: %s" % (m.channel, e), "err")
            return
        try:
            despues = m.raw_read_register(reg, 3).hex(" ")
        except Exception as e:
            despues = "ERR:%s" % e
        cambio = "CAMBIÓ" if antes != despues else "sin cambio"
        self._log_msg("Canal %s reg 0x%02X: %s → %s  [%s]"
                      % (m.channel, reg, antes, despues, cambio),
                      "ok" if antes != despues else "warn")

    def _raw_map(self):
        """Mapa del rango pedido. Solo lectura. Guarda y compara con el previo."""
        if not self._guard_idle():
            return
        try:
            n = max(1, min(64, int(self._raw_nbytes_var.get())))
        except ValueError:
            n = 3
        try:
            first = self._parse_int(self._raw_first_var.get()) & 0xFF
            last  = self._parse_int(self._raw_last_var.get()) & 0xFF
        except ValueError:
            messagebox.showerror("Mapa", "Rango inválido: usá 0x00–0xFF.")
            return
        if last < first:
            first, last = last, first
        if not hasattr(self, "_raw_map_prev"):
            self._raw_map_prev = {}

        targets = self._raw_targets()
        if not targets:
            messagebox.showinfo("Sin módulos",
                                "El módulo seleccionado ya no está disponible.\n"
                                "Volvé a escanear el bus USB.")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for m in targets:
            self._log_msg("── Mapa FPGA canal %s (%s) — 0x%02X a 0x%02X ──"
                          % (m.channel, m.serial, first, last), "info")
            mapa = m.raw_map_registers(first, last, n)
            prev = self._raw_map_prev.get(m.serial, {})
            n_diff = 0
            for reg in sorted(mapa):
                v = mapa[reg]
                if v.startswith("ERR:"):
                    continue
                marca = ""
                if prev and prev.get(reg) not in (None, v):
                    marca = "   <<< CAMBIÓ (antes %s)" % prev[reg]
                    n_diff += 1
                self._log_msg("  0x%02X : %s%s" % (reg, v, marca),
                              "warn" if marca else "info")
            self._raw_map_prev[m.serial] = mapa
            if prev:
                self._log_msg("  %d registro(s) cambiaron respecto del mapa anterior."
                              % n_diff, "ok" if n_diff else "info")

            # Persistir el mapa para análisis posterior
            try:
                path = "fpga_map_%s_%s.csv" % (m.serial.replace("+", ""), ts)
                with open(path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["register_hex", "register_dec", "raw_hex"])
                    for reg in sorted(mapa):
                        w.writerow(["0x%02X" % reg, reg, mapa[reg]])
                self._log_msg("  Mapa guardado: %s" % path, "ok")
            except Exception as e:
                self._log_msg("  No se pudo guardar el mapa: %s" % e, "warn")

    # ── Adquisición ─────────────────────────────────────────────────────

    def _report_acq(self, m, ok):
        """Hace visible un fallo de adquisición.

        `acquire()` se traga la excepción y la deja en `m.error`; sin esto el
        módulo simplemente desaparecía del gráfico sin decir nada, porque
        `_update_plot` saltea los que tienen `intensities is None`.

        Sólo loguea las transiciones OK↔fallo: en adquisición continua, un
        módulo caído inundaría el log a razón de varios mensajes por segundo.
        """
        if ok == (not m.acq_failed):
            return                      # sin cambio de estado: nada que decir
        m.acq_failed = not ok
        if ok:
            msg, lvl = ("✓ Canal %s (%s) volvió a adquirir."
                        % (m.channel, m.serial), "ok")
        else:
            msg, lvl = ("✗ Canal %s (%s) no adquirió: %s"
                        % (m.channel, m.serial, m.error), "err")
        self.after(0, lambda: self._log_msg(msg, lvl))

    def _single_shot(self):
        if not self.modules:
            messagebox.showinfo("Info", "No hay módulos conectados.")
            return
        ok_mods = [m for m in self.modules if m.spec is not None]
        if not ok_mods:
            messagebox.showerror("Error", "Ningún módulo operativo.")
            return
        self._log_msg("Adquiriendo un disparo…")
        for m in ok_mods:
            self._report_acq(m, m.acquire())
        self._update_plot()

    def _start_acquisition(self):
        if self._acquiring:
            return
        ok_mods = [m for m in self.modules if m.spec is not None]
        if not ok_mods:
            messagebox.showerror("Error", "No hay módulos operativos.")
            return
        self._acquiring = True
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._log_msg("Adquisición continua iniciada.")
        self._acq_thread = threading.Thread(
            target=self._acq_loop, daemon=True)
        self._acq_thread.start()

    def _stop_acquisition(self):
        self._acquiring = False
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        if self.modules:
            self._log_msg("Adquisición detenida.")

    def _acq_loop(self):
        t_last = time.time()
        frame_count = 0
        while self._acquiring:
            ok_mods = [m for m in self.modules if m.spec is not None]
            for m in ok_mods:
                self._report_acq(m, m.acquire())
            frame_count += 1
            elapsed = time.time() - t_last
            if elapsed >= 1.0:
                fps = frame_count / elapsed
                self.after(0, lambda f=fps: self._lbl_fps.configure(
                    text=f"{f:.1f} frames/s"))
                frame_count = 0
                t_last = time.time()
            self.after(0, self._update_plot)
            time.sleep(self._acq_interval_ms / 1000)

    # ── Actualizar gráfico ───────────────────────────────────────────────
    def _update_plot(self):
        if not MATPLOTLIB_OK:
            return
        self._ax.clear()
        self._style_ax()

        plotted = 0
        for m in self.modules:
            if not m._vis_var.get():
                continue
            if m.wavelengths is None or m.intensities is None:
                continue
            self._ax.plot(m.wavelengths, m.intensities,
                          color=m.color, linewidth=0.9,
                          label=f"Ch {m.channel} [{m.range_label}]")
            plotted += 1

        if plotted > 0:
            self._ax.legend(fontsize=7, facecolor="#21262D",
                            edgecolor="#30363D", labelcolor="#E6EDF3")
            self._ax.set_title(
                f"Espectro LIBS — {datetime.now().strftime('%H:%M:%S')}",
                color="#58A6FF", fontsize=10)
        else:
            self._ax.set_title("Sin datos — adquirí un espectro",
                               color="#8B949E", fontsize=10)

        self._fig.tight_layout(pad=1.5)
        self._canvas.draw_idle()

    # ── Exportar CSV ─────────────────────────────────────────────────────
    def _export_csv(self):
        ready = [m for m in self.modules
                 if m.wavelengths is not None and m.intensities is not None]
        if not ready:
            messagebox.showinfo("Info", "No hay datos para exportar.")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"espectro_{ts}.csv",
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")])
        if not path:
            return

        # Construir tabla: wavelength_A, intensity_A, wavelength_B, ...
        max_len = max(len(m.wavelengths) for m in ready)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            header = []
            for m in ready:
                header += [f"wl_ch{m.channel}_nm", f"int_ch{m.channel}_au"]
            writer.writerow(header)
            for i in range(max_len):
                row = []
                for m in ready:
                    if i < len(m.wavelengths):
                        row += [f"{m.wavelengths[i]:.4f}",
                                f"{m.intensities[i]:.2f}"]
                    else:
                        row += ["", ""]
                writer.writerow(row)

        self._log_msg(f"✓ Exportado: {os.path.basename(path)}", "ok")
        messagebox.showinfo("Exportado", f"Archivo guardado:\n{path}")

    # ── Cerrar limpiamente ───────────────────────────────────────────────
    def on_close(self):
        self._stop_acquisition()
        time.sleep(0.3)
        for m in self.modules:
            m.close()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Instrucciones de instalación (se muestran si faltan dependencias)
# ─────────────────────────────────────────────────────────────────────────────
INSTALL_MSG = """
╔══════════════════════════════════════════════════════════════════╗
║           OCEAN OPTICS — Panel de Control — Requisitos           ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  1. Instalar dependencias Python (64 bits):                      ║
║       pip install seabreeze matplotlib numpy libusb-package      ║
║                                                                  ║
║  2. Instalar driver WinUSB para cada módulo HR2000+:             ║
║       a. Descargar Zadig desde https://zadig.akeo.ie             ║
║       b. Conectar el rack USB del LIBS2500plus                   ║
║       c. En Zadig: Options → List All Devices                    ║
║       d. Seleccionar "Ocean Optics HR2000+"                      ║
║          (repetir para cada módulo que aparezca)                 ║
║       e. Driver destino: WinUSB — clic en "Replace Driver"       ║
║                                                                  ║
║  ¡NO instalar OOILIBSplus ni OceanView en esta PC!               ║
║  Esos programas cambian el driver a ezUSB y rompen seabreeze.    ║
║                                                                  ║
║  3. Ejecutar este programa:                                      ║
║       python ocean_control.py                                    ║
║                                                                  ║
║  Notas de seguridad:                                             ║
║  • Desenchufar módulos individuales del rack es SEGURO.          ║
║  • El firmware NO se corrompe por desconexión USB normal.        ║
║  • Solo corrompe si se interrumpe una actualización de firmware. ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""

if __name__ == "__main__":
    # Mostrar instrucciones en consola siempre.
    # La consola de Windows suele usar el codepage cp1252, que no puede
    # codificar los caracteres de dibujo de caja (╔ ║ etc.) de INSTALL_MSG
    # y tira UnicodeEncodeError antes de abrir la ventana. Reconfiguramos
    # stdout a UTF-8 (o, si no se puede, degradamos a ASCII) para evitarlo.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        print(INSTALL_MSG)
    except UnicodeEncodeError:
        print(INSTALL_MSG.encode("ascii", "replace").decode("ascii"))

    app = OceanControlApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
