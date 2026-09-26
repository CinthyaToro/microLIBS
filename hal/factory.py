# -*- coding: utf-8 -*-
"""
hal/factory.py
==============
Crea instancias de drivers (stage, cámara) por nombre.

Uso:
    from hal.factory import create_stage, create_camera
    stage = create_stage("movi")
    stage.connect({"port": "COM4", "baud": 115200})

NUEVO:
    from hal.factory import scan_movi_port, list_serial_ports
    port = scan_movi_port(log_fn=print)   # detecta el puerto MoVi automáticamente
    ports = list_serial_ports()           # lista todos los puertos disponibles
"""
from __future__ import annotations
from typing import Tuple


# Seriales de cámaras de producción cuyo mapa de defectos es obligatorio.
# Agregar aquí al incorporar nuevo hardware al labo.
KNOWN_PRODUCTION_SERIALS: frozenset = frozenset({11470397})


# ─── Stages ──────────────────────────────────────────────────────────────────

def create_stage(driver_name: str):
    """
    Crea y retorna una instancia del driver de stage indicado (sin conectar).
    Drivers disponibles: "movi", "thorlabs", "thorlabs_sim", "sim"
    """
    name = driver_name.strip().lower()
    if name == "movi":
        from hal.drivers.movi_stage import MoviStage
        return MoviStage()
    elif name == "thorlabs":
        try:
            from hal.drivers.thorlabs_stage import ThorlabsStage
            return ThorlabsStage()
        except ImportError:
            raise ImportError(
                "ThorlabsStage requiere pythonnet + Thorlabs Kinesis SDK.\n"
                "Instalar: pip install pythonnet  y el Kinesis SDK de Thorlabs."
            )
    elif name in ("thorlabs_sim", "sim"):
        from hal.drivers.sim_stage import SimStage
        return SimStage()
    else:
        raise ValueError(
            "Driver de stage desconocido: '%s'.\n"
            "Opciones válidas: 'movi', 'thorlabs', 'thorlabs_sim', 'sim'." % driver_name
        )


# ─── Rangos físicos por driver (mm) ─────────────────────────────────────────
STAGE_RANGES = {
    "movi":         (-35.0,  35.0, -35.0,  35.0),
    "thorlabs":     (  0.0,   4.0,   0.0,   4.0),
    "thorlabs_sim": (  0.0,   4.0,   0.0,   4.0),
    "sim":          (-50.0,  50.0, -50.0,  50.0),
}


def get_range(driver_name: str) -> Tuple[float, float, float, float]:
    """Retorna (x_min, x_max, y_min, y_max) en mm."""
    return STAGE_RANGES.get(driver_name.lower(), (-35.0, 35.0, -35.0, 35.0))


def get_range_note(driver_name: str) -> str:
    notes = {
        "movi":
            "MoVi: rango 35×35 mm. Origen variable (sin home de hardware).\n"
            "Coordenadas negativas son válidas.",
        "thorlabs":
            "Thorlabs: rango 4×4 mm. Home (0,0) = límite físico.\n"
            "Solo coordenadas positivas. Hacer Home antes de cada sesión.",
        "thorlabs_sim": "Thorlabs simulado: 4×4 mm, solo positivos.",
        "sim": "Stage simulado: acepta cualquier coordenada.",
    }
    return notes.get(driver_name.lower(), "Rango no especificado.")


def list_stage_drivers() -> list:
    return ["movi", "thorlabs", "thorlabs_sim", "sim"]


# ─── Utilidades de puerto serie ───────────────────────────────────────────────

def list_serial_ports() -> list:
    """
    Retorna lista de strings con todos los puertos serie disponibles.
    Ejemplo: ["COM3  (USB Serial Device)", "COM4"]  (Windows)
             ["/dev/ttyUSB0", "/dev/ttyACM0"]       (Linux)

    Útil para poblar un dropdown o menú de selección de puerto.
    """
    from hal.drivers.movi_stage import list_serial_ports as _list
    return _list()


def scan_movi_port(timeout_per_port: float = 2.5, log_fn=None) -> str:
    """
    Escanea todos los puertos serie disponibles y retorna el primero que
    responde como stage MoVi (respuesta contiene "listo").

    Parámetros:
        timeout_per_port  Tiempo máximo por puerto en segundos (default 2.5).
        log_fn            Función optional log_fn(str) para mostrar progreso
                          (por ejemplo: log_fn=print, o un callback de UI).

    Retorna:
        String del puerto (ej. "COM4") si se encontró.
        String vacío "" si no se encontró ningún MoVi.

    Uso típico desde UI (en hilo background):
        import threading
        def _detect():
            port = scan_movi_port(log_fn=ui_log)
            if port:
                root.after(0, lambda: port_var.set(port))
        threading.Thread(target=_detect, daemon=True).start()
    """
    from hal.drivers.movi_stage import find_movi_port
    return find_movi_port(timeout_per_port=timeout_per_port, log_fn=log_fn)


# ─── Cámaras ─────────────────────────────────────────────────────────────────

def create_camera(backend_kind: str, **kwargs):
    """
    Crea y retorna una instancia del backend de cámara indicado (sin abrir).
    Backends: "opencv", "chameleon", "sim_camera" (o "sim")
    """
    kind = backend_kind.strip().lower()
    if kind == "opencv":
        from hal.drivers.opencv_camera import OpenCVCamera
        return OpenCVCamera(index=kwargs.get("index", 0))
    elif kind == "chameleon":
        from pathlib import Path
        from paths import PROJECT_ROOT
        from hal.drivers.chameleon_camera import ChameleonCamera
        serial = int(kwargs["serial"])
        # Resolver mapa de defectos desde la raíz del proyecto por convención.
        # El caller puede sobreescribir pasando defect_map_path= explícito.
        defect_map_path = kwargs.get("defect_map_path")
        if defect_map_path is None:
            candidate = PROJECT_ROOT / "calibration" / ("chameleon_%d_defectmap.json" % serial)
            if candidate.exists():
                defect_map_path = str(candidate)
        require = serial in KNOWN_PRODUCTION_SERIALS
        return ChameleonCamera(
            serial=serial,
            dll_dir=kwargs.get("dll_dir",
                r"C:\Program Files\Point Grey Research\FlyCap2 Viewer\bin64"),
            warmup_frames=kwargs.get("warmup_frames", 10),
            defect_map_path=defect_map_path,
            require_defect_map=require,
        )
    elif kind in ("sim_camera", "sim"):
        from hal.drivers.sim_camera import SimCamera
        calib_path = kwargs.get("calibration_image_path")
        # Si no se proporciona explícitamente, buscar última calibración
        if calib_path is None:
            calib_path = _find_latest_calibration_image()
        return SimCamera(
            width=kwargs.get("width", 640),
            height=kwargs.get("height", 480),
            calibration_image_path=calib_path,
        )
    else:
        raise ValueError("Backend de cámara desconocido: '%s'" % backend_kind)


def list_camera_backends() -> list:
    return ["opencv", "chameleon", "sim_camera"]


def _find_latest_calibration_image() -> str | None:
    """
    Busca la imagen PNG más reciente en data_libs/ (por timestamp en nombre).
    Patrón esperado: libs_YYYYMMDD_HHMMSS.png
    Retorna la ruta completa si existe, None en caso contrario.

    Util para SimCamera: la última captura de calibración se usa por defecto.
    El usuario puede cambiarla después con set_calibration_image().
    """
    from pathlib import Path
    import os

    data_dir = Path("data_libs")
    if not data_dir.exists():
        return None

    # Buscar todos los PNG con patrón libs_*.png
    pngs = sorted(data_dir.glob("libs_*.png"), key=os.path.getmtime, reverse=True)
    if pngs:
        return str(pngs[0])  # El más reciente

    return None


# ─── Láseres ─────────────────────────────────────────────────────────────────

def create_laser(driver_name: str, **kwargs):
    """
    Crea y retorna una instancia del driver de láser indicado (sin conectar).

    Drivers disponibles:
        "ekspla"    — EKSPLA NL230 vía LaserProxy → laser_server.py (32-bit)
        "sim_laser" — SimLaser para testing sin hardware

    El objeto retornado implementa BaseLaser. Para conectar al hardware:
        laser = create_laser("ekspla")
        laser.connect({
            "host":            "127.0.0.1",
            "port":            27182,
            "connection_type": "usb",
        })
    """
    name = driver_name.strip().lower()
    if name == "ekspla":
        from hal.drivers.laser_proxy import LaserProxy
        return LaserProxy()
    elif name in ("sim_laser", "sim"):
        from hal.drivers.sim_laser import SimLaser
        return SimLaser(
            fire_delay_s=kwargs.get("fire_delay_s", 0.05)
        )
    else:
        raise ValueError(
            "Driver de láser desconocido: '%s'.\n"
            "Opciones válidas: 'ekspla', 'sim_laser'." % driver_name
        )


def list_laser_drivers() -> list:
    return ["ekspla", "sim_laser"]

# ─── Espectrómetros ───────────────────────────────────────────────────────────

def create_spectrometer(driver_name: str = "ocean", **kwargs):
    name = driver_name.strip().lower()
    if name in ("ocean", "ocean_optics", "libs2500"):
        from hal.drivers.ocean_spectrometer import OceanSpectrometer
        return OceanSpectrometer()
    elif name in ("sim", "sim_spectrometer"):
        from hal.drivers.sim_spectrometer import SimSpectrometer
        return SimSpectrometer(rng_seed=kwargs.get("rng_seed", 42))
    else:
        raise ValueError(
            "Driver de espectrómetro desconocido: '%s'.\n"
            "Opciones: 'ocean', 'sim'." % driver_name
        )

def list_spectrometer_drivers() -> list:
    return ["ocean", "sim"]

