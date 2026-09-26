#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analizar_espectros.py — Ver y analizar espectros LIBS del scan (microLIBS).

Resuelve los dos problemas que complicaban en Excel:
  1. El CSV tiene metadata en las primeras 4 columnas (#, timestamp, integration_ms,
     trigger_mode) y el espectro en las columnas 5-10 (wl/int de canales A, B, C).
  2. El separador decimal: lee los números directo, sin depender de la config regional
     de Excel (que en es-AR toma el "." como separador de miles y rompe todo).

USO:
    python analizar_espectros.py                 # analiza los CSV de la carpeta actual
    python analizar_espectros.py <carpeta>       # analiza los CSV de esa carpeta
    python analizar_espectros.py archivo.csv     # analiza un solo archivo

Genera:
  - Una tabla en consola con baseline, máximo, longitud de onda del pico y nσ por canal.
  - Un PNG con los espectros graficados (un panel por archivo, 3 canales en color).

Requiere: matplotlib  (pip install matplotlib)
"""

import sys
import os
import csv
import glob
import statistics

try:
    import matplotlib
    matplotlib.use("Agg")  # sin ventana; guarda PNG. Sacá esta línea si querés ventana.
    import matplotlib.pyplot as plt
    HAY_PLOT = True
except Exception:
    HAY_PLOT = False

# Columnas del CSV: 0=#, 1=timestamp, 2=integration_ms, 3=trigger_mode,
#                   4=wl_chA, 5=int_chA, 6=wl_chB, 7=int_chB, 8=wl_chC, 9=int_chC
COLS = {"A": (4, 5), "B": (6, 7), "C": (8, 9)}
COLOR = {"A": "#1f9bd6", "B": "#5fcf3f", "C": "#e8821e"}  # azul / verde / naranja
SIGMA_PICO = 8.0  # umbral en sigmas para declarar "pico real"


def _to_float(s):
    """Convierte a float tolerando coma decimal o espacios. Devuelve None si no puede."""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        try:
            return float(s.replace(",", "."))
        except ValueError:
            return None


def leer_csv(path):
    """Devuelve {'A': (wl[], int[]), 'B': (...), 'C': (...)} salteando filas no numéricas."""
    chans = {ch: ([], []) for ch in COLS}
    with open(path, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 10:
                continue
            for ch, (wi, ii) in COLS.items():
                w = _to_float(row[wi])
                v = _to_float(row[ii])
                if w is not None and v is not None:
                    chans[ch][0].append(w)
                    chans[ch][1].append(v)
    return chans


def stats_canal(wl, it):
    """baseline (mediana), max, wl@max, delta, nσ (sigma robusto vía MAD)."""
    if not it:
        return None
    base = statistics.median(it)
    mad = statistics.median([abs(x - base) for x in it]) or 1.0
    sigma = 1.4826 * mad  # MAD → sigma para ruido gaussiano
    mx = max(it)
    imx = it.index(mx)
    delta = mx - base
    nsig = delta / sigma if sigma else 0.0
    return {"base": base, "max": mx, "wl_max": wl[imx], "delta": delta, "nsig": nsig}


def analizar(paths):
    print("=" * 78)
    print(f"{'archivo':<28} {'ch':>2} {'base':>6} {'max':>7} {'wl@max':>8} "
          f"{'Δ':>6} {'nσ':>6}  pico?")
    print("-" * 78)
    resultados = []
    for path in paths:
        nombre = os.path.basename(path)
        chans = leer_csv(path)
        resultados.append((path, nombre, chans))
        primera = True
        for ch in "ABC":
            wl, it = chans[ch]
            st = stats_canal(wl, it)
            if st is None:
                continue
            flag = "★ PLASMA" if st["nsig"] > SIGMA_PICO else "baseline"
            etiqueta = nombre if primera else ""
            primera = False
            print(f"{etiqueta:<28} {ch:>2} {st['base']:>6.0f} {st['max']:>7.0f} "
                  f"{st['wl_max']:>8.2f} {st['delta']:>6.0f} {st['nsig']:>6.1f}  {flag}")
        print("-" * 78)
    return resultados


def graficar(resultados, salida="espectros.png"):
    if not HAY_PLOT:
        print("\n(matplotlib no está instalado; salteo el gráfico. "
              "Instalá con: pip install matplotlib)")
        return
    n = len(resultados)
    fig, axes = plt.subplots(n, 1, figsize=(11, 3.2 * n), squeeze=False)
    for k, (path, nombre, chans) in enumerate(resultados):
        ax = axes[k][0]
        for ch in "ABC":
            wl, it = chans[ch]
            if it:
                ax.plot(wl, it, color=COLOR[ch], lw=0.8, label=f"Ch {ch}")
        ax.set_title(nombre, fontsize=9)
        ax.set_ylabel("Intensidad (u.a.)", fontsize=8)
        ax.legend(fontsize=7, loc="upper right")
        ax.grid(alpha=0.25)
    axes[-1][0].set_xlabel("Longitud de onda (nm)", fontsize=8)
    fig.tight_layout()
    fig.savefig(salida, dpi=130)
    print(f"\nGráfico guardado en: {os.path.abspath(salida)}")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "."
    if os.path.isdir(arg):
        paths = sorted(glob.glob(os.path.join(arg, "espectro_*.csv")))
        if not paths:
            paths = sorted(glob.glob(os.path.join(arg, "*.csv")))
    elif os.path.isfile(arg):
        paths = [arg]
    else:
        print(f"No encontré '{arg}'.")
        return 1

    if not paths:
        print("No hay CSV para analizar en esa ubicación.")
        return 1

    resultados = analizar(paths)
    carpeta = arg if os.path.isdir(arg) else os.path.dirname(arg) or "."
    graficar(resultados, salida=os.path.join(carpeta, "espectros.png"))
    print("\nNota: 'nσ' es cuántas desviaciones sobre el fondo está el máximo.")
    print(f"      > {SIGMA_PICO:.0f}σ = pico real de plasma;  ~3-4σ = baseline (ruido).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
