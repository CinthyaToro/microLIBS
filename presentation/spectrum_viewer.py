"""
spectrum_viewer.py — Visualizador en tiempo real de espectros HR2000+

Uso básico:
    viewer = SpectrumViewer(root_tk)

    # Mostrar dark (sin laser):
    viewer.update(dark_dict, "dark")

    # Mostrar raw (con laser):
    viewer.update(raw_dict, "raw")

    # Mostrar neto (raw - dark):
    viewer.update(neto_dict, "neto")

    # Limpiar todos los espectros:
    viewer.clear()

Formato de spectrum_dict (igual al que devuelve spec.acquire()):
    {
        "ok": True,
        "channels": {
            "A": {"wavelengths": [...], "intensities": [...], "serial": "HR+C1911"},
            "B": {"wavelengths": [...], "intensities": [...], "serial": "HR+C1914"},
            "C": {"wavelengths": [...], "intensities": [...], "serial": "HR+C1915"},
        }
    }

Thread-safety: update() puede llamarse desde cualquier hilo daemon.
"""

import threading
import tkinter as tk

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ── Paleta de colores por tipo de espectro ────────────────────────────────────
STYLE = {
    "dark":  {"color": "#888899", "lw": 1.0, "alpha": 0.75, "zorder": 1},
    "raw":   {"color": "#378ADD", "lw": 1.2, "alpha": 0.90, "zorder": 2},
    "neto":  {"color": "#1D9E75", "lw": 1.4, "alpha": 0.95, "zorder": 3},
}

# Canal → rango λ y color del título
CANAL_META = {
    "A": {"label": "Canal A  (UV · 293–390 nm · C1911)", "title_color": "#7B9FCC"},
    "B": {"label": "Canal B  (VIS · 519–636 nm · C1914)", "title_color": "#7BC4A0"},
    "C": {"label": "Canal C  (NIR · 624–729 nm · C1915)", "title_color": "#C4A07B"},
}

CHANNEL_ORDER = ["A", "B", "C"]


class SpectrumViewer:
    """
    Ventana Toplevel con 3 subplots (uno por canal del HR2000+).
    Se actualiza en tiempo real desde cualquier hilo.
    Si la ventana se cierra, se recrea al próximo update().
    """

    def __init__(self, root: tk.Tk):
        self._root   = root
        self._win    = None
        self._fig    = None
        self._axes   = {}       # canal → Axes
        self._lines  = {}       # (tipo, canal) → Line2D
        self._canvas = None
        self._lock   = threading.Lock()

        if not HAS_MPL:
            print("WARN spectrum_viewer: matplotlib no disponible, viewer deshabilitado.")

    # ── API pública ───────────────────────────────────────────────────────────

    def update(self, spectrum: dict, label: str = "raw"):
        """
        Actualiza el plot con un nuevo espectro. Thread-safe.

        spectrum : dict con estructura {"channels": {"A": {...}, ...}}
        label    : "dark" | "raw" | "neto"
        """
        if not HAS_MPL or spectrum is None:
            return
        self._root.after(0, lambda: self._do_update(spectrum, label))

    def clear(self):
        """Elimina todas las líneas del plot. Thread-safe."""
        if not HAS_MPL:
            return
        self._root.after(0, self._do_clear)

    def show(self):
        """Trae la ventana al frente si existe."""
        self._root.after(0, self._bring_to_front)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _ensure_window(self):
        """Crea (o recrea) la ventana si no existe o fue cerrada."""
        if self._win is not None:
            try:
                if self._win.winfo_exists():
                    return
            except Exception:
                pass
        self._create_window()

    def _create_window(self):
        win = tk.Toplevel(self._root)
        win.title("microLIBS — Espectrómetro en vivo")
        win.geometry("920x640")
        win.configure(bg="#1a1a2e")

        # Botones de control
        btn_frame = tk.Frame(win, bg="#1a1a2e")
        btn_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(6, 0))

        tk.Button(
            btn_frame, text="Limpiar",
            bg="#333355", fg="white", activebackground="#444477",
            relief=tk.FLAT, padx=12,
            command=self._do_clear,
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            btn_frame, text="Acercar (todo)",
            bg="#333355", fg="white", activebackground="#444477",
            relief=tk.FLAT, padx=12,
            command=self._autoscale_all,
        ).pack(side=tk.LEFT, padx=4)

        self._status_var = tk.StringVar(value="Sin espectro aún.")
        tk.Label(
            btn_frame, textvariable=self._status_var,
            bg="#1a1a2e", fg="#888899", font=("Courier", 9),
        ).pack(side=tk.LEFT, padx=12)

        # Figura matplotlib
        fig = Figure(figsize=(9, 5.5), dpi=100)
        fig.patch.set_facecolor("#1a1a2e")
        fig.subplots_adjust(hspace=0.5, left=0.08, right=0.97, top=0.95, bottom=0.07)

        axes = {}
        for i, ch in enumerate(CHANNEL_ORDER):
            ax = fig.add_subplot(3, 1, i + 1)
            ax.set_facecolor("#0d0d1a")
            ax.tick_params(colors="#666688", labelsize=7)
            ax.set_ylabel("Cuentas", color="#666688", fontsize=7)
            for spine in ax.spines.values():
                spine.set_edgecolor("#222244")
            meta = CANAL_META.get(ch, {})
            ax.set_title(meta.get("label", f"Canal {ch}"),
                         color=meta.get("title_color", "#aaaacc"),
                         fontsize=8, pad=3)
            ax.axhline(0, color="#333355", linewidth=0.6, linestyle=":")
            axes[ch] = ax

        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.get_tk_widget().configure(bg="#1a1a2e")
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Toolbar navegación matplotlib (zoom, pan, guardar)
        toolbar_frame = tk.Frame(win, bg="#1a1a2e")
        toolbar_frame.pack(side=tk.BOTTOM, fill=tk.X)
        toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
        toolbar.configure(bg="#1a1a2e")
        toolbar.update()

        # Leyenda fija
        legend_frame = tk.Frame(win, bg="#1a1a2e")
        legend_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=2)
        for lbl, st in STYLE.items():
            tk.Label(
                legend_frame,
                text=f"■ {lbl}",
                fg=st["color"], bg="#1a1a2e", font=("Courier", 9),
            ).pack(side=tk.LEFT, padx=8)

        self._win    = win
        self._fig    = fig
        self._axes   = axes
        self._canvas = canvas
        self._lines  = {}

    def _do_update(self, spectrum: dict, label: str):
        """Ejecuta en el hilo de UI (vía root.after)."""
        self._ensure_window()

        channels = spectrum.get("channels", {})
        style    = STYLE.get(label, STYLE["raw"])
        picos    = []

        for ch in CHANNEL_ORDER:
            ch_data = channels.get(ch)
            if not ch_data:
                continue

            wls  = ch_data.get("wavelengths") or ch_data.get("wavelength") or []
            ints = ch_data.get("intensities") or ch_data.get("intensity") or []

            if not wls or not ints:
                continue

            ax  = self._axes.get(ch)
            if ax is None:
                continue

            key = (label, ch)

            # Remover línea anterior del mismo tipo
            if key in self._lines:
                try:
                    self._lines[key].remove()
                except Exception:
                    pass

            line, = ax.plot(
                wls, ints,
                color=style["color"],
                linewidth=style["lw"],
                alpha=style["alpha"],
                zorder=style["zorder"],
            )
            self._lines[key] = line

            # Ajustar escala Y automáticamente
            ax.relim()
            ax.autoscale_view(scalex=False)

            # Pico máximo
            if ints:
                idx_max = ints.index(max(ints))
                max_v   = ints[idx_max]
                max_wl  = wls[idx_max] if idx_max < len(wls) else "?"
                picos.append(f"ch{ch}: {max_v:.0f}cts @ {max_wl:.1f}nm")

        status = f"{label.upper()}  |  " + "   ".join(picos) if picos else f"{label.upper()} actualizado"
        self._status_var.set(status)
        self._canvas.draw_idle()

    def _do_clear(self):
        """Elimina todas las líneas. Ejecuta en hilo de UI."""
        self._ensure_window()
        for key, line in list(self._lines.items()):
            try:
                line.remove()
            except Exception:
                pass
        self._lines.clear()
        for ax in self._axes.values():
            ax.relim()
            ax.autoscale_view()
        if self._status_var:
            self._status_var.set("Plot limpiado.")
        if self._canvas:
            self._canvas.draw_idle()

    def _autoscale_all(self):
        self._ensure_window()
        for ax in self._axes.values():
            ax.relim()
            ax.autoscale_view()
        if self._canvas:
            self._canvas.draw_idle()

    def _bring_to_front(self):
        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
