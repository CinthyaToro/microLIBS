# -*- coding: utf-8 -*-
"""
tests/test_golden_sim.py
=========================
Golden run del pipeline microLIBS en modo 100% simulado.

CORRIDA FUNDACIONAL — dia cero del golden run de microLIBS v1 (2026-05-31).
Esta regresion es sim-contra-sim: fotografia el comportamiento del simulador
de hoy, NO valida senal espectral real. No confundir con validacion de hardware.
El estado actual del sistema -con sus bugs conocidos- es la baseline a proposito.

Ejecutar:
    python -m pytest tests/test_golden_sim.py -v

Salida esperada:
- Primera corrida (bootstrap): 3 PASSED + 2 SKIPPED + golden JSON/CSV impresos.
  Revisa los artefactos generados y da el OK para commitear.
- Corridas siguientes: 5 PASSED, exit code 0.
"""

import json
import os
import pathlib

import numpy as np
import pytest

GOLDEN_DIR          = pathlib.Path(__file__).parent / "golden"
FROZEN_PLAN_PATH    = GOLDEN_DIR / "scan_plan_frozen.json"
GOLDEN_SUMMARY_PATH = GOLDEN_DIR / "scan_summary_golden.json"
GOLDEN_SPECTRA_PATH = GOLDEN_DIR / "spectra_golden.csv"

N_POINTS = 3


# ── Fixture de corrida unica ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def golden_run(tmp_path_factory):
    """
    Ejecuta el pipeline completo UNA vez en simulacion y expone los outputs.
    Todos los tests del modulo comparten esta corrida (scope=module).
    """
    from service.vision_service import VisionService, CameraDescriptor
    from hal.drivers.sim_stage import SimStage
    from hal.drivers.sim_laser import SimLaser
    from hal.drivers.ocean_spectrometer import OceanSpectrometer
    from service.scan_service import ScanRunner

    tmp = tmp_path_factory.mktemp("golden_run")
    session_dir = tmp / "session"
    images_dir  = tmp / "session" / "images"
    events_dir  = tmp / "session" / "events"
    for d in (session_dir, images_dir, events_dir):
        d.mkdir(parents=True, exist_ok=True)
    # spectra/ lo crea SpectrometerStep automaticamente dentro de session_dir

    with open(FROZEN_PLAN_PATH, encoding="utf-8") as f:
        pts = json.load(f)["points"]
    assert len(pts) == N_POINTS, "scan_plan_frozen.json debe tener exactamente 3 puntos"

    # ── Hardware simulado ──────────────────────────────────────────────────────
    svc = VisionService()
    svc.set_selected(CameraDescriptor(kind="sim_camera", id="sim", label="SimCamera"))

    stage = SimStage()
    stage.connect({})

    spec = OceanSpectrometer()
    spec.connect({
        "simulate":       True,
        "rng_seed":       42,           # determinismo garantizado
        "trigger_mode":   0,            # FREE_RUNNING: no espera trigger HW
        "integration_us": 2100,
        "n_channels":     3,
        # Seleccion EXPLICITA por serial, no por posicion. Sin esto, el driver
        # toma "los primeros 3" de sim_ranges y basta con insertar un modulo en
        # el medio del perfil para que el golden compare otros modulos sin que
        # nadie lo note (paso con HR+C1912 en el commit 7b0b3df).
        # Este trio es el de config/sim_iberolibs.yaml y lab_iberolibs.yaml.
        "modulos_activos": ["HR+C1911", "HR+C1914", "HR+C1915"],
        "output_dir":     str(session_dir),  # SpectrometerStep lo sobreescribe
    })

    laser = SimLaser(fire_delay_s=0.0)
    laser.connect({})
    laser.arm()  # LaserStep no arma por defecto (arm_each=False); hay que pre-armar

    runner = ScanRunner(
        vc=svc,
        stage=stage,
        images_dir=str(images_dir),
        events_dir=str(events_dir),
        session_dir=str(session_dir),
        sample_name="golden_test",
        operator="pytest",
        settle_s=0.0,
        use_sim_dwell=False,    # camino real: LaserStep + SpectrometerStep
        laser=laser,
        spectrometer=spec,
        spectrometer_params={"integration_ms": 2.1, "averages": 1},
        stop_on_error=True,
    )

    runner.start(pts)
    runner.join(timeout=30)
    assert not runner.running, "ScanRunner no termino en 30 s — posible deadlock"

    dirs = {
        "session": session_dir,
        "images":  images_dir,
        "events":  events_dir,
        "spectra": session_dir / "spectra",  # creado por SpectrometerStep
    }
    yield dirs

    # teardown
    try:   svc.close()
    except Exception: pass
    try:   laser.disconnect()
    except Exception: pass
    try:   spec.disconnect()
    except Exception: pass


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_01_imports_clean():
    """Todos los modulos del pipeline importan sin excepciones (SyntaxError, TabError, etc.)."""
    from service.scan_service import (ScanRunner, MoveStep, SettleStep, CaptureStep,
                                      LaserStep, SpectrometerStep, SimDwellStep, FocusStep)
    from service.vision_service import VisionService, CameraDescriptor
    from hal.drivers.sim_camera import SimCamera
    from hal.drivers.sim_stage import SimStage
    from hal.drivers.sim_laser import SimLaser
    from hal.drivers.ocean_spectrometer import OceanSpectrometer
    from hal.factory import create_stage, create_spectrometer, create_laser


def test_02_scanrunner_visits_all_points(golden_run):
    """ScanRunner visita los 3 puntos, no genera errores, y guarda scan_summary.json."""
    events_dir   = golden_run["events"]
    summary_path = events_dir / "scan_summary.json"

    assert summary_path.exists(), "scan_summary.json no fue generado"

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    assert summary["total_points"] == N_POINTS
    assert summary["error"] == 0, \
        f"Hubo puntos con ERROR (esperaba 0): {summary}"
    assert summary["ok"] + summary["warn"] == N_POINTS

    point_files = list(events_dir.glob("point_*.json"))
    assert len(point_files) == N_POINTS, \
        f"Esperaba {N_POINTS} archivos point_*.json, encontre {len(point_files)}"


def test_03_captures_exist_and_nonempty(golden_run):
    """
    Pre y post imagen existen por cada punto y tienen tamano > 1 KB.
    Comparacion de contenido de pixel: TODO (otro commit).
    """
    images_dir = golden_run["images"]
    images = (list(images_dir.glob("*.png")) +
              list(images_dir.glob("*.jpg")) +
              list(images_dir.glob("*.tiff")))

    assert len(images) >= 2 * N_POINTS, \
        f"Esperaba >= {2 * N_POINTS} imagenes (pre+post x punto), encontre {len(images)}"

    for img in images:
        size = img.stat().st_size
        assert size > 1024, \
            f"Imagen vacia o demasiado pequeña ({size} B): {img.name}"


def _load_spectral_data(csv_path: str) -> np.ndarray:
    """
    Lee las filas de datos espectrales del CSV producido por OceanSpectrometer._save_csv().
    Salta la fila de encabezado (fila 0) y la fila de metadatos (fila 1, tiene timestamp).
    Retorna array float de shape (n_filas, n_columnas_numericas).
    """
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < 2:   # header + metadata con timestamp
                continue
            parts = line.strip().split(",")
            # Las primeras 4 columnas (#, timestamp, integration_ms, trigger_mode)
            # estan vacias en las filas de datos
            nums = []
            for p in parts[4:]:
                p = p.strip()
                if p:
                    try:
                        nums.append(float(p))
                    except ValueError:
                        nums.append(0.0)
            if nums:
                rows.append(nums)
    return np.array(rows, dtype=float) if rows else np.array([])


@pytest.mark.skip(reason=(
    "Golden de v2.1 (IBEROLIBS26), JUBILADO: no es una regresion sin resolver. "
    "spectra_golden.csv fotografio el simulador del 31-May-2026 para el objetivo "
    "'1 espectro de microplasticos por SCAN', que se cumplio y se presento en el "
    "congreso. Desde agosto/2026 el objetivo es otro, y el golden de v2.2 se arma "
    "de cero contra el simulador de esta etapa. "
    "PARA REVIVIRLO: sacar este skip, borrar tests/golden/spectra_golden.csv y "
    "correr el test dos veces (la 1a hace bootstrap y avisa, la 2a compara). "
    "El CSV de v2.1 queda versionado como referencia historica. "
    "DIFERENCIA MEDIDA contra el simulador actual (22-Sep-2026): canales C "
    "(HR+C1914) y D (HR+C1915) bit-identicos en las 2048 filas; solo cambia el "
    "canal A (HR+C1911), porque 7b0b3df recalibro su arranque de 294.00 a "
    "293.83 nm."
))
def test_04_spectra_csv_vs_golden(golden_run):
    """
    Regresion sim-contra-sim: compara el primer CSV de espectro producido
    contra el golden generado en la corrida fundacional (2026-05-31, rng_seed=42).

    IMPORTANTE: este test NO valida senal espectral real. Es una fotografia
    del comportamiento del simulador con seed fijo. Sirve para detectar
    regresiones involuntarias en el pipeline de adquisicion simulada
    (cambios en OceanSpectrometer, _sim_spectrum, SpectrometerStep, etc.).

    Tolerancia: atol=1.0 cuenta, rtol=1e-4.
    Intensidades en cuentas, 16 bits, full scale 65535 (TCD1304).
    1 cuenta es una tolerancia ajustada y correcta para este detector.
    """
    spectra_dir = golden_run["spectra"]
    assert spectra_dir.exists(), \
        "Directorio spectra/ no creado — SpectrometerStep no corrio"

    csv_files = sorted(spectra_dir.glob("espectro_*.csv"))
    assert len(csv_files) > 0, "No se genero ningun CSV de espectro"

    produced = _load_spectral_data(str(csv_files[0]))
    assert produced.size > 0, f"CSV vacio: {csv_files[0].name}"

    if not GOLDEN_SPECTRA_PATH.exists():
        import shutil
        shutil.copy2(str(csv_files[0]), str(GOLDEN_SPECTRA_PATH))
        print(f"\n=== BOOTSTRAP spectra_golden.csv ===")
        print(f"Forma: {produced.shape}  (filas x columnas numericas)")
        print(f"Primeras 3 filas de datos:")
        for row in produced[:3]:
            print("  " + "  ".join(f"{v:10.4f}" for v in row))
        print(f"Max intensidad: {produced[:, 1::2].max():.1f}")
        print(f"Min intensidad: {produced[:, 1::2].min():.1f}")
        print(f"\nArchivo guardado en: {GOLDEN_SPECTRA_PATH}")
        print(">>> Revisa el archivo y da el OK para commitear <<<")
        pytest.skip("BOOTSTRAP spectra_golden.csv — revisa y da el OK")

    golden = _load_spectral_data(str(GOLDEN_SPECTRA_PATH))
    assert produced.shape == golden.shape, \
        f"Shape cambio: producido={produced.shape} vs golden={golden.shape}"
    assert np.allclose(produced, golden, atol=1.0, rtol=1e-4), \
        (f"Espectro difiere del golden.\n"
         f"  Max diff absoluta: {np.max(np.abs(produced - golden)):.4f} cuentas\n"
         f"  Posicion: fila={np.unravel_index(np.argmax(np.abs(produced - golden)), produced.shape)}")


def _normalize_summary(data: dict) -> dict:
    """Elimina campos no-deterministas (timestamps) del scan_summary para comparacion JSON."""
    return {k: v for k, v in data.items()
            if k not in ("started_iso", "finished_iso")}


def test_05_summary_json_vs_golden(golden_run):
    """
    Regresion sim-contra-sim: estructura y conteos del scan_summary.
    Timestamps excluidos. Verifica: total_points, ok, warn, error.
    """
    summary_path = golden_run["events"] / "scan_summary.json"
    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    normalized = _normalize_summary(summary)

    if not GOLDEN_SUMMARY_PATH.exists():
        GOLDEN_SUMMARY_PATH.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"\n=== BOOTSTRAP scan_summary_golden.json ===")
        print(json.dumps(normalized, indent=2, ensure_ascii=False))
        print(f"\nArchivo guardado en: {GOLDEN_SUMMARY_PATH}")
        print(">>> Revisa el archivo y da el OK para commitear <<<")
        pytest.skip("BOOTSTRAP scan_summary_golden.json — revisa y da el OK")

    with open(GOLDEN_SUMMARY_PATH, encoding="utf-8") as f:
        golden = json.load(f)

    assert normalized == golden, \
        (f"scan_summary difiere del golden.\n"
         f"  Producido: {normalized}\n"
         f"  Golden:    {golden}")
