# -*- coding: utf-8 -*-
"""
tools/figuras_paper.py
======================
Genera las figuras de arquitectura del manuscrito para LIBS-Spectra.

    Figure1  Diagrama de capas, con el punto de corte de la abstracción
    Figure2  Diagrama de secuencia del ciclo de medición sobre un punto

Requisitos de la revista que esto cumple:
  · 600 dpi para diagramas y dibujo lineal
  · formato PNG
  · archivos independientes con nombre limpio (Figure1.png, Figure2.png)
  · ancho útil de página A4 con márgenes estándar (~17 cm)

Diseñadas en escala de grises a propósito: se leen igual impresas en blanco y
negro, que es como las mira un revisor.

Uso:
    python tools/figuras_paper.py
    python tools/figuras_paper.py --dpi 600 --out docs/paper/figuras
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import PROJECT_ROOT                       # noqa: E402

# Objetivo: 17 cm de ancho útil (A4 con márgenes estándar) DESPUÉS del recorte
# de márgenes que hace bbox_inches="tight". El recorte se lleva ~18 %, así que
# se compensa en el lienzo para que el archivo final mida lo que debe medir.
ANCHO_CM_OBJETIVO = 17.0
ANCHO_IN = (ANCHO_CM_OBJETIVO * 1.22) / 2.54

# Paleta en gris: se distingue por valor, no por color.
GRIS_BORDE = "#1a1a1a"
GRIS_TEXTO = "#1a1a1a"
RELLENO_ALTO = "#e8e8e8"     # capas por encima del corte
RELLENO_BAJO = "#f7f7f7"     # capas por debajo
RELLENO_REAL = "#d0d0d0"     # controlador de instrumento real
RELLENO_GEMELO = "#ffffff"   # gemelo simulado
BANDA = "#dcdcdc"


def _caja(ax, x, y, w, h, relleno, lw=1.0, estilo="round,pad=0.0,rounding_size=1.2"):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=estilo,
        linewidth=lw, edgecolor=GRIS_BORDE, facecolor=relleno,
        mutation_aspect=0.6, zorder=2))


# ─────────────────────────────────────────────────────────────────────────────
#  Figura 1 — capas
# ─────────────────────────────────────────────────────────────────────────────

CAPAS = [
    ("Interfaz de usuario",
     "presenta y recoge; no decide nada del experimento", RELLENO_ALTO),
    ("Orquestación",
     "recorre los puntos, ordena las operaciones, decide el cierre", RELLENO_ALTO),
    ("Dominio",
     "técnicas (LIBS) y procedimientos (fondo, foco, retardo)", RELLENO_ALTO),
    ("Capacidades",
     "posicionar · registrar imagen · disparar · adquirir", RELLENO_ALTO),
]

CAPACIDADES = [
    ("Posicionar",       "Thorlabs\nMoVi",                  "gemelo\nde platina"),
    ("Registrar imagen", "Chameleon\nCelestron\nweb",        "gemelo\nde cámara"),
    ("Disparar",         "EKSPLA\nNL230",                   "gemelo\nde láser"),
    ("Adquirir",         "HR2000+\n(× 4)",                  "gemelo\nde espectr."),
]


def figura_capas(path: Path, dpi: int) -> None:
    fig, ax = plt.subplots(figsize=(ANCHO_IN, ANCHO_IN * 0.78))
    ax.set_xlim(0, 100)
    ax.axis("off")

    x0, ancho = 11.0, 84.0
    alto, sep = 7.6, 2.4
    y = 96.0

    for titulo, detalle, relleno in CAPAS:
        y -= alto
        _caja(ax, x0, y, ancho, alto, relleno)
        ax.text(x0 + 2.4, y + alto * 0.62, titulo,
                fontsize=9.5, fontweight="bold", color=GRIS_TEXTO, va="center")
        ax.text(x0 + 2.4, y + alto * 0.24, detalle,
                fontsize=7.8, style="italic", color="#444444", va="center")
        y -= sep

    # ── Punto de corte ────────────────────────────────────────────────────────
    y_corte = y - 4.0
    ax.plot([x0 - 4, x0 + ancho + 4], [y_corte, y_corte],
            linestyle=(0, (5, 3)), linewidth=1.5, color=GRIS_BORDE, zorder=3)
    ax.text(x0 + ancho + 4, y_corte + 1.6, "punto de corte de la abstracción",
            fontsize=8.2, fontweight="bold", color=GRIS_TEXTO, ha="right")
    ax.text(x0 + ancho + 4, y_corte - 3.2,
            "arriba no se nombra ninguna marca   ·   abajo cada archivo conoce un solo instrumento",
            fontsize=7.2, style="italic", color="#444444", ha="right")

    # ── Capa de controladores, abierta en cuatro capacidades ─────────────────
    y_ctrl_top = y_corte - 7.5
    alto_ctrl = 29.0
    y_ctrl = y_ctrl_top - alto_ctrl
    _caja(ax, x0, y_ctrl, ancho, alto_ctrl, RELLENO_BAJO)
    ax.text(x0 + 2.4, y_ctrl_top - 3.2, "Controladores",
            fontsize=9.5, fontweight="bold", color=GRIS_TEXTO, va="center")
    ax.text(x0 + 2.4, y_ctrl_top - 6.6,
            "cada instrumento entra con su gemelo: es un paso de la integración, no un modo de uso",
            fontsize=7.4, style="italic", color="#444444", va="center")

    n = len(CAPACIDADES)
    margen = 1.6
    w_col = (ancho - margen * (n + 1)) / n
    alto_par = 11.6
    y_par = y_ctrl + 4.2
    for i, (cap, real, gemelo) in enumerate(CAPACIDADES):
        xc = x0 + margen + i * (w_col + margen)
        ax.text(xc + w_col / 2, y_par + alto_par + 2.4, cap,
                fontsize=8.2, fontweight="bold", color=GRIS_TEXTO,
                ha="center", va="center")
        w_sub = (w_col - 1.2) / 2
        _caja(ax, xc, y_par, w_sub, alto_par, RELLENO_REAL, lw=0.9,
              estilo="round,pad=0.0,rounding_size=0.8")
        ax.text(xc + w_sub / 2, y_par + alto_par / 2, real,
                fontsize=5.8, color=GRIS_TEXTO, ha="center", va="center",
                linespacing=1.4)
        ax.text(xc + w_sub / 2, y_par - 2.0, "real",
                fontsize=6.6, style="italic", color="#444444", ha="center")

        xg = xc + w_sub + 1.2
        _caja(ax, xg, y_par, w_sub, alto_par, RELLENO_GEMELO, lw=0.9,
              estilo="round,pad=0.0,rounding_size=0.8")
        ax.text(xg + w_sub / 2, y_par + alto_par / 2, gemelo,
                fontsize=5.8, color=GRIS_TEXTO, ha="center", va="center",
                linespacing=1.4)
        ax.text(xg + w_sub / 2, y_par - 2.0, "simulado",
                fontsize=6.6, style="italic", color="#444444", ha="center")

    # ── Hardware ─────────────────────────────────────────────────────────────
    y_hw = y_ctrl - sep - alto
    _caja(ax, x0, y_hw, ancho, alto, RELLENO_BAJO)
    ax.text(x0 + 2.4, y_hw + alto * 0.50, "Hardware",
            fontsize=9.5, fontweight="bold", color=GRIS_TEXTO, va="center")

    # ── Flecha de dependencia ────────────────────────────────────────────────
    ax.add_patch(FancyArrowPatch(
        (6.0, 95.5), (6.0, y_hw + 0.6),
        arrowstyle="-|>", mutation_scale=13,
        linewidth=1.2, color=GRIS_BORDE, zorder=4))
    ax.text(3.2, (95.5 + y_hw) / 2, "dependencia",
            fontsize=7.8, color="#444444", rotation=90,
            ha="center", va="center")

    ax.set_ylim(y_hw - 3.0, 99.0)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
#  Figura 2 — secuencia del ciclo sobre un punto
# ─────────────────────────────────────────────────────────────────────────────

ACTORES = ["Orquestación", "Platina", "Cámara", "Láser", "Espectrómetro"]

#  (origen, destino, texto, crítico)   índices sobre ACTORES
PASOS = [
    (0, 1, "mover a (x, y)", False),
    (0, 0, "estabilizar", False),
    (0, 2, "micrografía previa", False),
    (0, 4, "armar la adquisición (hilo separado)", True),
    (0, 3, "disparar la ráfaga", True),
    (3, 4, "un pulso de sincronismo por disparo", True),
    (0, 0, "esperar con techo de tiempo", True),
    (0, 2, "micrografía posterior", False),
    (0, 0, "persistir el punto", False),
]


def figura_secuencia(path: Path, dpi: int) -> None:
    fig, ax = plt.subplots(figsize=(ANCHO_IN, ANCHO_IN * 0.70))
    ax.set_xlim(0, 100)
    ax.axis("off")

    xs = [10.0, 31.0, 50.0, 67.5, 88.0]
    y_top = 89.0
    paso_dy = 8.4

    # Banda del tramo crítico, detrás de todo
    idx_crit = [i for i, p in enumerate(PASOS) if p[3]]
    y_paso = [y_top - 10.0 - i * paso_dy for i in range(len(PASOS))]
    y_banda_top = y_paso[idx_crit[0]] + 5.4
    y_banda_bot = y_paso[idx_crit[-1]] - 3.4
    ax.add_patch(Rectangle(
        (2.0, y_banda_bot), 96.0, y_banda_top - y_banda_bot,
        facecolor=BANDA, edgecolor=GRIS_BORDE, linewidth=0.9,
        linestyle=(0, (4, 2.5)), zorder=0))
    y_bot = y_paso[-1] - 4.0

    # Cabeceras y líneas de vida
    for x, nombre in zip(xs, ACTORES):
        _caja(ax, x - 9.8, y_top, 19.6, 6.4, RELLENO_ALTO, lw=1.0,
              estilo="round,pad=0.0,rounding_size=1.0")
        ax.text(x, y_top + 3.2, nombre, fontsize=7.9, fontweight="bold",
                color=GRIS_TEXTO, ha="center", va="center")
        ax.plot([x, x], [y_bot, y_top], linestyle=(0, (2, 2.6)),
                linewidth=0.9, color="#777777", zorder=1)

    for i, (a, b, texto, critico) in enumerate(PASOS):
        y = y_paso[i]
        lw = 1.5 if critico else 1.0
        if a == b:
            # auto-mensaje: pequeño lazo a la derecha de la línea de vida
            x = xs[a]
            ax.add_patch(FancyArrowPatch(
                (x, y + 1.5), (x, y - 1.5),
                connectionstyle="arc3,rad=-1.9", arrowstyle="-|>",
                mutation_scale=10, linewidth=lw, color=GRIS_BORDE, zorder=3))
            ax.text(x + 5.2, y, texto, fontsize=7.8,
                    color=GRIS_TEXTO, ha="left", va="center")
        else:
            x1, x2 = xs[a], xs[b]
            ax.add_patch(FancyArrowPatch(
                (x1, y), (x2, y), arrowstyle="-|>", mutation_scale=11,
                linewidth=lw, color=GRIS_BORDE, zorder=3))
            ax.text((x1 + x2) / 2, y + 1.7, texto, fontsize=7.6,
                    color=GRIS_TEXTO, ha="center", va="bottom")

    # Nota del invariante, debajo de todos los pasos
    ax.text(50.0, y_bot - 4.0,
            "Orden obligatorio: el espectrómetro debe estar escuchando antes del primer pulso.",
            fontsize=8.0, fontweight="bold", color=GRIS_TEXTO, ha="center")
    ax.text(50.0, y_bot - 7.4,
            "Invertirlo pierde el dato: la señal de sincronismo llega mientras nadie la espera.",
            fontsize=7.6, style="italic", color="#444444", ha="center")

    ax.set_ylim(y_bot - 10.5, 97.5)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
#  Figura 3 — Ishikawa 6M adaptado
# ─────────────────────────────────────────────────────────────────────────────

# estado: 0 = controlada · 1 = variable menor · 2 = no dominada
ESPINAS_ARRIBA = [
    ("Máquina", [("Platina", 0),
                 ("Cámara y lentes", 0),
                 ("Láser: energía y λ", 2)]),
    ("Método", [("N.º de pulsos por punto", 1),
                ("Criterio de validez", 1),
                ("Enfoque del láser", 2)]),
    ("Medición", [("Espectrómetro", 0),
                  ("Calibración px↔mm", 0)]),
]
ESPINAS_ABAJO = [
    ("Medio ambiente", [("Vibraciones", 1),
                        ("Temperatura, humedad", 1)]),
    ("Mano de obra", [("Alineación manual", 1),
                      ("Capacitación", 1)]),
    ("Materiales", [("Absorción a λ", 0),
                    ("Rugosidad superficial", 1)]),
]

CABEZA = "Resolución\nespacial efectiva\ndel mapa"

_MARCA = {0: ("o", "white"), 1: ("o", "#9a9a9a"), 2: ("o", GRIS_BORDE)}


def _espina(ax, x_base, arriba, titulo, causas):
    """Dibuja una espina con su rótulo y sus causas."""
    signo = 1 if arriba else -1
    y0, y1 = 50.0, 50.0 + signo * 30.0
    x1 = x_base - 13.0
    ax.plot([x_base, x1], [y0, y1], linewidth=1.3, color=GRIS_BORDE, zorder=2)

    _caja(ax, x1 - 9.0, y1 + (1.5 if arriba else -7.5), 18.0, 6.0, RELLENO_ALTO,
          lw=1.0, estilo="round,pad=0.0,rounding_size=1.0")
    ax.text(x1, y1 + (4.5 if arriba else -4.5), titulo, fontsize=8.0,
            fontweight="bold", color=GRIS_TEXTO, ha="center", va="center")

    for i, (texto, estado) in enumerate(causas):
        t = 0.34 + 0.24 * i
        xc = x_base + (x1 - x_base) * t
        yc = y0 + (y1 - y0) * t
        marcador, relleno = _MARCA[estado]
        ax.plot([xc], [yc], marcador, markersize=4.2, markerfacecolor=relleno,
                markeredgecolor=GRIS_BORDE, markeredgewidth=0.9, zorder=3)
        ax.text(xc + 1.8, yc, texto, fontsize=6.3,
                fontweight="bold" if estado == 2 else "normal",
                color=GRIS_TEXTO, ha="left", va="center")


def figura_ishikawa(path: Path, dpi: int) -> None:
    fig, ax = plt.subplots(figsize=(ANCHO_IN, ANCHO_IN * 0.52))
    ax.set_xlim(0, 100)
    ax.set_ylim(6, 94)
    ax.axis("off")

    # Espina dorsal
    ax.add_patch(FancyArrowPatch((5.0, 50.0), (73.0, 50.0), arrowstyle="-|>",
                                 mutation_scale=16, linewidth=1.8,
                                 color=GRIS_BORDE, zorder=2))
    _caja(ax, 73.5, 43.0, 24.0, 14.0, RELLENO_ALTO, lw=1.4)
    ax.text(85.5, 50.0, CABEZA, fontsize=8.0, fontweight="bold",
            color=GRIS_TEXTO, ha="center", va="center", linespacing=1.3)

    for i, (titulo, causas) in enumerate(ESPINAS_ARRIBA):
        _espina(ax, 31.0 + i * 21.0, True, titulo, causas)
    for i, (titulo, causas) in enumerate(ESPINAS_ABAJO):
        _espina(ax, 31.0 + i * 21.0, False, titulo, causas)

    # Referencias
    for j, (etiqueta, estado) in enumerate(
            [("controlada", 0), ("variable menor", 1), ("sin dominar", 2)]):
        x = 6.0 + j * 21.0
        marcador, relleno = _MARCA[estado]
        ax.plot([x], [8.5], marcador, markersize=4.2, markerfacecolor=relleno,
                markeredgecolor=GRIS_BORDE, markeredgewidth=0.9)
        ax.text(x + 1.8, 8.5, etiqueta, fontsize=7.0,
                fontweight="bold" if estado == 2 else "normal",
                color="#444444", ha="left", va="center")

    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dpi", type=int, default=600,
                    help="resolución de salida (la revista pide 600 para diagramas)")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "docs" / "paper" / "figuras"))
    args = ap.parse_args()

    salida = Path(args.out)
    salida.mkdir(parents=True, exist_ok=True)

    f1 = salida / "Figure1.png"
    f2 = salida / "Figure2.png"
    f3 = salida / "Figure3.png"
    figura_capas(f1, args.dpi)
    figura_secuencia(f2, args.dpi)
    figura_ishikawa(f3, args.dpi)

    for f in (f1, f2, f3):
        print("  %-14s %7.0f kB" % (f.name, f.stat().st_size / 1024))
    print("\nEscrito en %s  (%d dpi)" % (salida, args.dpi))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
