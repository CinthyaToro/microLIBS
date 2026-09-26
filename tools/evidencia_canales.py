# -*- coding: utf-8 -*-
"""
tools/evidencia_canales.py
==========================
Evidencia reproducible para el resultado «independencia del número de canales».

Corre el MISMO pipeline de scan, con el MISMO orquestador y el MISMO plan de
puntos, cambiando únicamente cuántos módulos espectrales hay:

    4 canales · 3 canales · 1 canal · sin espectrómetro

Si el orquestador fuera sensible al número de canales, alguna de esas corridas
fallaría o produciría un resumen distinto. La afirmación del artículo es que no
lo es, y esto es lo que la sostiene.

Todo corre contra los gemelos simulados: no necesita hardware.

Uso:
    python tools/evidencia_canales.py
    python tools/evidencia_canales.py --out docs/paper/evidencia

Deja dos archivos en el directorio de salida:
    evidencia_canales.json  — datos crudos de cada corrida
    evidencia_canales.md    — la tabla lista para el manuscrito
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paths import PROJECT_ROOT  # noqa: E402

PLAN_PATH = PROJECT_ROOT / "tests" / "golden" / "scan_plan_frozen.json"

# Los cuatro módulos del rack, por serial. El orden es el de config/*.yaml.
MODULOS = ["HR+C1911", "HR+C1912", "HR+C1914", "HR+C1915"]

CASOS = [
    ("4 canales",         4),
    ("3 canales",         3),
    ("1 canal",           1),
    ("sin espectrómetro", 0),
]


def _correr_caso(etiqueta: str, n_canales: int, puntos: list, raiz: Path) -> dict:
    """Corre un scan completo en simulación y devuelve el resumen medido."""
    from service.vision_service import VisionService, CameraDescriptor
    from service.scan_service import ScanRunner
    from hal.factory import create_stage, create_laser, create_spectrometer

    base = raiz / etiqueta.replace(" ", "_")
    session_dir = base / "session"
    images_dir = session_dir / "images"
    events_dir = session_dir / "events"
    for d in (session_dir, images_dir, events_dir):
        d.mkdir(parents=True, exist_ok=True)

    svc = VisionService()
    svc.set_selected(CameraDescriptor(kind="sim_camera", id="sim", label="SimCamera"))

    stage = create_stage("sim")
    stage.connect({})

    laser = create_laser("sim_laser", fire_delay_s=0.0)
    laser.connect({})
    laser.arm()

    spec = None
    if n_canales > 0:
        spec = create_spectrometer("sim")
        spec.connect({
            "trigger_mode":    0,                     # free-running: no espera TTL
            "integration_us":  2100,
            "n_channels":      n_canales,
            # Selección por IDENTIDAD, no por posición. Ver R6 en CLAUDE.md.
            "modulos_activos": MODULOS[:n_canales],
            "output_dir":      str(session_dir),
        })

    runner = ScanRunner(
        vc=svc,
        stage=stage,
        images_dir=str(images_dir),
        events_dir=str(events_dir),
        session_dir=str(session_dir),
        sample_name="evidencia_canales",
        operator="tools/evidencia_canales.py",
        settle_s=0.0,
        use_sim_dwell=False,
        laser=laser,
        spectrometer=spec,
        spectrometer_params={"integration_ms": 2.1, "averages": 1},
        stop_on_error=True,
    )

    runner.start(puntos)
    runner.join(timeout=60)
    termino = not runner.running

    resumen_path = events_dir / "scan_summary.json"
    resumen = {}
    if resumen_path.exists():
        resumen = json.loads(resumen_path.read_text(encoding="utf-8"))

    # Búsqueda recursiva a propósito: el driver real escribe en session/spectra/,
    # pero el gemelo simulado no honra la redirección y deja los CSV en la raíz de
    # la sesión (ver docs/bitacora). Se registra DÓNDE aparecieron, que es el dato.
    csvs = sorted(session_dir.rglob("espectro_*.csv"))
    ubicaciones = sorted({str(p.parent.relative_to(session_dir)) or "." for p in csvs})
    imagenes = sorted(images_dir.glob("*.png"))

    # Cuántas columnas de datos trae el primer CSV: 2 por canal (λ e intensidad).
    columnas = None
    if csvs:
        with open(csvs[0], encoding="utf-8") as f:
            for i, linea in enumerate(f):
                if i == 2:  # 0 = encabezado, 1 = metadata, 2 = primera fila de datos
                    celdas = [c for c in linea.strip().split(",")[4:] if c.strip()]
                    columnas = len(celdas)
                    break

    for cerrar in (svc.close, laser.disconnect, getattr(spec, "disconnect", lambda: None)):
        try:
            cerrar()
        except Exception:
            pass

    return {
        "caso":                etiqueta,
        "n_canales":           n_canales,
        "modulos":             MODULOS[:n_canales],
        "termino_sin_colgar":  termino,
        "puntos_totales":      resumen.get("total_points"),
        "puntos_ok":           resumen.get("ok"),
        "puntos_warn":         resumen.get("warn"),
        "puntos_error":        resumen.get("error"),
        "espectros_csv":       len(csvs),
        "csv_en":              ubicaciones,
        "columnas_datos_csv":  columnas,
        "imagenes":            len(imagenes),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(PROJECT_ROOT / "docs" / "paper" / "evidencia"),
                    help="Directorio donde dejar el JSON y la tabla Markdown")
    args = ap.parse_args()

    salida = Path(args.out)
    salida.mkdir(parents=True, exist_ok=True)

    puntos = json.loads(PLAN_PATH.read_text(encoding="utf-8"))["points"]

    raiz = Path(tempfile.mkdtemp(prefix="evidencia_canales_"))
    filas = []
    try:
        for etiqueta, n in CASOS:
            print("  corriendo: %-20s" % etiqueta, end="", flush=True)
            fila = _correr_caso(etiqueta, n, puntos, raiz)
            filas.append(fila)
            print("  ok=%s error=%s espectros=%s" % (
                fila["puntos_ok"], fila["puntos_error"], fila["espectros_csv"]))
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    entorno = {
        "fecha":     datetime.now().isoformat(timespec="seconds"),
        "python":    sys.version.split()[0],
        "plataforma": platform.platform(),
        "plan":      str(PLAN_PATH.relative_to(PROJECT_ROOT)),
        "puntos":    len(puntos),
    }

    (salida / "evidencia_canales.json").write_text(
        json.dumps({"entorno": entorno, "corridas": filas}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    lineas = [
        "# Evidencia — independencia del número de canales",
        "",
        "Generado por `tools/evidencia_canales.py`. Todo en simulación, sin hardware.",
        "",
        "| Fecha | Python | Plan | Puntos |",
        "|---|---|---|---|",
        "| %s | %s | `%s` | %d |" % (entorno["fecha"], entorno["python"],
                                     entorno["plan"], entorno["puntos"]),
        "",
        "| Caso | Módulos | Puntos ok | warn | error | Espectros | Columnas CSV | Imágenes | CSV en |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for f in filas:
        lineas.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            f["caso"],
            ", ".join(f["modulos"]) if f["modulos"] else "—",
            f["puntos_ok"], f["puntos_warn"], f["puntos_error"],
            f["espectros_csv"],
            f["columnas_datos_csv"] if f["columnas_datos_csv"] is not None else "—",
            f["imagenes"],
            ", ".join("`%s`" % u for u in f["csv_en"]) if f["csv_en"] else "—"))
    lineas += [
        "",
        "**Cómo leerla.** El plan de puntos, el orquestador y el código del scan son",
        "los mismos en las cuatro filas: lo único que cambia es cuántos módulos",
        "espectrales se declaran. Las columnas del CSV son dos por canal (longitud de",
        "onda e intensidad), así que su número verifica que se escribió lo declarado.",
        "",
    ]
    (salida / "evidencia_canales.md").write_text("\n".join(lineas), encoding="utf-8")

    print("\nEscrito en %s" % salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
