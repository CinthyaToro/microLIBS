# -*- coding: utf-8 -*-
"""
spec_pipeline.py  —  Procesado espectral puro (sin hardware, sin UI)
=====================================================================
Funciones:
    subtract_dark   — resta dark a un canal, floor en 0
    normalize       — normaliza un array de intensidades
    save_channel    — guarda CSV + JSON metadata por canal
    load_darks      — carga darks desde directorio
    report_snr      — imprime tabla dark/señal/ratio por canal
    plot_channels   — grafica canales con hueco 390–520 nm marcado

Formato CSV:  wavelength_nm, intensity_counts  (una fila por píxel)
Formato JSON: metadata del canal (serial, rango, int_us, n_avg, timestamp, etc.)

Hueco de cobertura de este sistema: 390–520 nm (ningún módulo lo cubre).
"""

from __future__ import print_function

import csv
import json
import os
from datetime import datetime

GAP_NM = (390, 520)   # hueco sin cobertura entre canal A y canal B

CHANNEL_COLORS = {"A": "#00BFFF", "B": "#FF8C00", "C": "#BF5FFF"}

Y_LABELS = {
    "counts":   "Intensidad (cuentas)",
    "per_ms":   "Intensidad (cuentas / ms)",
    "minmax":   "Intensidad (norm. 0–1)",
    "baseline": "Intensidad (baseline = 0)",
}


# ─── Procesado ────────────────────────────────────────────────────────────────

def subtract_dark(raw_ch, dark_ch, clip_negative=False):
    """
    Resta dark a un canal. Ambos son dicts con clave "intensities".
    Retorna nuevo dict con intensidades restadas.

    clip_negative=False (default): conserva valores negativos (física correcta,
        permite ver ruido por debajo del dark y detectar errores de medición).
    clip_negative=True: aplica floor en 0 (comportamiento legacy, útil cuando
        el consumidor downstream no admite negativos).
    """
    r = raw_ch["intensities"]
    d = dark_ch["intensities"]
    if len(r) != len(d):
        raise ValueError(
            "Canal %s: raw=%d puntos, dark=%d puntos" % (
                raw_ch.get("channel", "?"), len(r), len(d))
        )
    out = dict(raw_ch)
    if clip_negative:
        out["intensities"] = [max(0.0, ri - di) for ri, di in zip(r, d)]
    else:
        out["intensities"] = [ri - di for ri, di in zip(r, d)]
    out["dark_subtracted"] = True
    return out


def normalize(intensities, mode="per_ms", int_us=None):
    """
    Normaliza un array de intensidades.

    Modos:
        counts    sin cambios (cuentas crudas)
        per_ms    divide por tiempo de integración en ms → cuentas/ms
        minmax    escala al rango [0, 1] por canal
        baseline  resta el mínimo → piso en 0
    """
    if mode == "counts":
        return list(intensities)

    if mode == "per_ms":
        if not int_us:
            raise ValueError("normalize(per_ms) requiere int_us")
        f = max(int_us, 1) / 1000.0
        return [v / f for v in intensities]

    if mode == "minmax":
        mn, mx = min(intensities), max(intensities)
        rng = mx - mn if mx != mn else 1.0
        return [(v - mn) / rng for v in intensities]

    if mode == "baseline":
        mn = min(intensities)
        return [v - mn for v in intensities]

    raise ValueError("Modo de normalización desconocido: %s" % mode)


# ─── Persistencia ─────────────────────────────────────────────────────────────

def save_channel(ch_data, out_dir, prefix="espectro"):
    """
    Guarda un canal como CSV + JSON metadata.

    Nombre de archivo: {prefix}_{timestamp}_ch{A|B|C}_{serial}_{int_us}us.{csv|json}
    Retorna el path del CSV guardado.
    """
    os.makedirs(out_dir, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = "%s_%s_ch%s_%s_%dus" % (
        prefix, ts,
        ch_data["channel"], ch_data["serial"], ch_data["int_us"],
    )
    csv_path  = os.path.join(out_dir, base + ".csv")
    json_path = os.path.join(out_dir, base + ".json")

    wls  = ch_data["wavelengths"]
    ints = ch_data["intensities"]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["wavelength_nm", "intensity_counts"])
        for wl, it in zip(wls, ints):
            w.writerow(["%.4f" % wl, "%.2f" % it])

    meta = {
        "channel":         ch_data["channel"],
        "serial":          ch_data["serial"],
        "range_nm":        [round(wls[0], 4), round(wls[-1], 4)],
        "int_us":          ch_data["int_us"],
        "n_avg":           ch_data.get("n_avg", 1),
        "timestamp":       ch_data.get("timestamp", ts),
        "type":            prefix,
        "dark_subtracted": ch_data.get("dark_subtracted", False),
        "n_points":        len(wls),
        "csv_file":        os.path.basename(csv_path),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return csv_path


def load_darks(dark_dir, int_us=None):
    """
    Carga darks desde un directorio.

    Para cada canal (A, B, C) selecciona:
      - el dark de int_us más cercano si int_us es dado
      - el más reciente (por nombre) si int_us es None

    Retorna dict {channel_letter: ch_data} o {} si no hay darks.
    """
    if not os.path.isdir(dark_dir):
        return {}

    entries = []
    for fname in os.listdir(dark_dir):
        if not (fname.startswith("dark_") and fname.endswith(".json")):
            continue
        try:
            with open(os.path.join(dark_dir, fname), encoding="utf-8") as f:
                meta = json.load(f)
            entries.append((fname, meta))
        except Exception:
            continue

    if not entries:
        return {}

    by_ch = {}
    for fname, meta in entries:
        ch = meta.get("channel")
        if ch:
            by_ch.setdefault(ch, []).append((fname, meta))

    result = {}
    for ch, items in by_ch.items():
        if int_us is not None:
            items.sort(key=lambda x: abs(x[1].get("int_us", 0) - int_us))
        else:
            items.sort(key=lambda x: x[0], reverse=True)

        fname, meta = items[0]
        csv_path = os.path.join(dark_dir, meta["csv_file"])
        if not os.path.isfile(csv_path):
            continue

        wls, ints = [], []
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)   # saltar encabezado
            for row in reader:
                try:
                    wls.append(float(row[0]))
                    ints.append(float(row[1]))
                except (ValueError, IndexError):
                    pass

        result[ch] = {
            "channel":     ch,
            "serial":      meta["serial"],
            "wavelengths": wls,
            "intensities": ints,
            "int_us":      meta["int_us"],
            "n_avg":       meta.get("n_avg", 1),
            "timestamp":   meta.get("timestamp", ""),
            "type":        "dark",
        }

    return result


# ─── Reporte ──────────────────────────────────────────────────────────────────

def report_snr(dark_chs, signal_chs):
    """Imprime tabla dark / señal / ratio por canal."""
    print("  %-6s %-10s %8s %8s %7s  %s" % (
        "Canal", "Serial", "Dark", "Señal", "Ratio", "Diagnóstico"))
    print("  " + "-" * 60)
    for ch in sorted(signal_chs):
        sig  = signal_chs[ch]
        dark = dark_chs.get(ch)
        s_mean = sum(sig["intensities"]) / len(sig["intensities"])
        if dark:
            d_mean = sum(dark["intensities"]) / len(dark["intensities"])
            ratio  = s_mean / d_mean if d_mean > 0 else float("inf")
        else:
            d_mean, ratio = 0.0, float("nan")

        if ratio > 1.5:        diag = "señal presente"
        elif ratio > 1.1:      diag = "señal marginal"
        elif ratio != ratio:   diag = "(sin dark)"   # nan
        else:                  diag = "sin señal detectable"

        print("  Ch%-4s %-10s %8.0f %8.0f %7.2f  %s" % (
            ch, sig["serial"], d_mean, s_mean, ratio, diag))


# ─── Graficado ────────────────────────────────────────────────────────────────

def plot_channels(channel_list, gap_nm=GAP_NM, title="", norm_mode="counts", int_us=None):
    """
    Grafica todos los canales en un mismo eje, con el hueco 390–520 nm marcado.

    channel_list: lista de dicts de canal (con wavelengths e intensities)
    norm_mode:    ver normalize()
    int_us:       requerido si norm_mode == 'per_ms'
    """
    try:
        import matplotlib
        matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib no disponible — pip install matplotlib)")
        return

    fig, ax = plt.subplots(figsize=(11, 5))
    fig.patch.set_facecolor("#0D1117")
    ax.set_facecolor("#010409")

    # Banda del hueco
    ax.axvspan(gap_nm[0], gap_nm[1], color="#1C2128", alpha=0.9, zorder=0)
    ax.text(
        (gap_nm[0] + gap_nm[1]) / 2.0, 0.97,
        "sin cobertura\n%d–%d nm" % gap_nm,
        transform=ax.get_xaxis_transform(),
        ha="center", va="top", fontsize=7, color="#484F58", style="italic",
    )

    for ch_data in channel_list:
        ch   = ch_data["channel"]
        i_us = int_us or ch_data.get("int_us", 1)
        try:
            ints = normalize(ch_data["intensities"], norm_mode, i_us)
        except Exception:
            ints = ch_data["intensities"]
        color = CHANNEL_COLORS.get(ch, "#FFFFFF")
        label = "Ch %s  %s  [%.0f–%.0f nm]" % (
            ch, ch_data["serial"],
            ch_data["wavelengths"][0], ch_data["wavelengths"][-1],
        )
        ax.plot(ch_data["wavelengths"], ints, color=color, linewidth=0.9, label=label)

    ax.set_xlabel("Longitud de onda (nm)", color="#8B949E", fontsize=9)
    ax.set_ylabel(Y_LABELS.get(norm_mode, "Intensidad"), color="#8B949E", fontsize=9)
    ax.set_title(title or "Espectro LIBS2500plus", color="#58A6FF", fontsize=10)
    ax.tick_params(colors="#8B949E", labelsize=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("bottom", "left"):
        ax.spines[s].set_color("#30363D")
    ax.grid(True, color="#21262D", linestyle="--", linewidth=0.5)
    ax.legend(fontsize=8, facecolor="#21262D", edgecolor="#30363D", labelcolor="#E6EDF3")
    plt.tight_layout()
    plt.show()
