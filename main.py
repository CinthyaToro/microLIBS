# -*- coding: utf-8 -*-
"""
main.py — punto de entrada de microLIBS v2 (FIXED)
=================================================
"""

import os
import sys
import time
import yaml
import argparse
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

# Red de seguridad: fuerza UTF-8 en stdout para que cualquier print() con
# caracteres no-ASCII no crashee en terminales Windows cp1252.
# La causa raiz (emojis en scan_service.py) ya esta arreglada; esto es respaldo.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from application.session_manager import SessionManager
from application.step0_wizard import Step0Wizard
from hal.factory import create_stage, create_laser, create_spectrometer
from presentation.main_window import show_session_wizard, open_control_panel
from service.vision_service import VisionService


def _parse_args():
    """Parsea argumentos de CLI con argparse."""
    parser = argparse.ArgumentParser(
        description="microLIBS v2 — Espectrometría elemental por LIBS",
        prog="python main.py"
    )
    parser.add_argument(
        "--config",
        default="default_experiment.yaml",
        help="YAML de configuración a cargar (default: default_experiment.yaml)"
    )
    return parser.parse_args()


def _list_available_configs(config_dir):
    """Lista archivos .yaml disponibles en la carpeta de config."""
    try:
        yaml_files = sorted(p.name for p in config_dir.glob("*.yaml"))
        return yaml_files if yaml_files else []
    except Exception:
        return []


def main():
    root = tk.Tk()
    root.withdraw()

    svc     = VisionService()
    mgr     = SessionManager()
    initial = mgr.load_settings()

    # ─────────────────────────────────────────────────────────────
    # 0. Cargar configuración YAML
    # ─────────────────────────────────────────────────────────────
    from paths import PROJECT_ROOT

    args = _parse_args()
    config_dir = PROJECT_ROOT / "config"
    cfg_path = config_dir / args.config

    # Validar que el archivo exista
    if not cfg_path.exists():
        available = _list_available_configs(config_dir)
        msg = f"No encontré {args.config}.\n"
        if available:
            msg += f"Configs disponibles:\n  - " + "\n  - ".join(available)
        else:
            msg += "No hay archivos .yaml en la carpeta config/."
        print(msg)
        sys.exit(1)

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            exp_cfg = yaml.safe_load(f) or {}
        print(f"[Config] Cargado: {cfg_path}")
    except Exception as e:
        print(f"[Config] Error al leer {cfg_path}: {e}")
        sys.exit(1)

    exp_cfg = exp_cfg or {}

    # ─────────────────────────────────────────────────────────────
    # 1. Wizard
    # ─────────────────────────────────────────────────────────────
    w = show_session_wizard(root, initial, svc)
    if not w.get("ok"):
        print("Sesión cancelada.")
        try: svc.close()
        except Exception: pass
        return

    # ─────────────────────────────────────────────────────────────
    # 2. Validar carpeta base
    # ─────────────────────────────────────────────────────────────
    try:
        SessionManager.validate_base_dir(w["base_dir"])
    except ValueError as e:
        messagebox.showerror("Carpeta base", str(e))
        try: svc.close()
        except Exception: pass
        return

    # ─────────────────────────────────────────────────────────────
    # 3. Crear sesión
    # ─────────────────────────────────────────────────────────────
    mgr.create(w["base_dir"], w["sample_name"], w.get("operator", ""))

    # ─────────────────────────────────────────────────────────────
    # 4. Stage
    # ─────────────────────────────────────────────────────────────
    stage_driver = w.get("stage_driver", "thorlabs_sim")
    stage = None

    try:
        stage = create_stage(stage_driver)
        stage.connect({
            "port":      w.get("stage_port", "COM4"),
            "baud":      115200,
            "serial_no": "",
        })
        print(f"Stage '{stage_driver}' conectado OK.")
    except Exception as e:
        print(f"WARN stage '{stage_driver}': {e}")
        stage = None

    # ─────────────────────────────────────────────────────────────
    # 5. Laser
    # ─────────────────────────────────────────────────────────────
    laser_driver = w.get("laser_driver", "none").lower()
    laser = None

    if laser_driver not in ("none", "", "ninguno"):
        try:
            laser = create_laser(laser_driver)
            laser.connect({
                "host":            w.get("laser_host", "127.0.0.1"),
                "port":            int(w.get("laser_port", 27182)),
                "connection_type": w.get("laser_conn_type", "usb"),
                "lan_host":        "",
                "auto_arm":        False,
            })
            print(f"Laser '{laser_driver}' conectado OK.")
        except Exception as e:
            print(f"WARN laser '{laser_driver}': {e}")
            laser = None

    # ─────────────────────────────────────────────────────────────
    # 6. Spectrometer (FIX REAL)
    # ─────────────────────────────────────────────────────────────
    spectrometer = None
    spec_cfg = exp_cfg.get("spectrometer", {})

    if spec_cfg.get("driver") not in (None, "", "none"):
        try:
            spectrometer = create_spectrometer(
                spec_cfg.get("driver", "ocean")
            )

            spectrometer.connect({
                "trigger_mode":     spec_cfg.get("trigger_mode", 4),
                "integration_us":   spec_cfg.get("integration_us", 5000),
                "n_channels":       spec_cfg.get("n_channels", 4),
                "modulos_activos":  spec_cfg.get("modulos_activos"),
                "module_timeout_s": spec_cfg.get("module_timeout_s", 40),
                "output_dir":       mgr.session_dir,
                "simulate":         spec_cfg.get("driver") == "sim",
            })

            print("Spectrometer conectado OK.")

        except Exception as e:
            import traceback
            print("WARN spectrometer:", repr(e))
            traceback.print_exc()
            spectrometer = None

    # ─────────────────────────────────────────────────────────────
    # 7. Banner de poka-yoke (estado real de drivers)
    # ─────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("[ESTADO] Configuración cargada y hardware conectado:")
    print("="*70)
    print(f"[Config] YAML: {cfg_path}")

    # Spectrometer
    spec_drv = spec_cfg.get("driver", "ninguno").lower()
    if spectrometer and spectrometer.is_connected:
        spec_info = f"spectrometer: {spec_drv} (CONECTADO)"
        if spec_drv == "ocean":
            modulos = spec_cfg.get("modulos_activos", [])
            if modulos:
                spec_info += f" — seriales: {modulos}"
    elif spec_drv == "sim":
        spec_info = f"spectrometer: {spec_drv} (SIMULADO)"
    elif spec_drv in ("none", "ninguno", ""):
        spec_info = f"spectrometer: ninguno configurado"
    else:
        spec_info = (f"spectrometer: {spec_drv} (ERROR DE CONEXIÓN — "
                      f"revisar 'WARN spectrometer:' más arriba en la consola)")
    print(f"[HW] {spec_info}")

    # Laser
    if laser and laser.is_connected:
        print(f"[HW] laser: {laser_driver} (CONECTADO - HARDWARE REAL)")
    elif laser:
        print(f"[HW] laser: {laser_driver} (error de conexión)")
    else:
        print(f"[HW] laser: {laser_driver} (SIMULADO o ninguno)")

    # Stage
    if stage:
        print(f"[HW] stage: {stage_driver} (OK)")
    else:
        print(f"[HW] stage: {stage_driver} (sin conectar)")

    print("="*70 + "\n")

    # ─────────────────────────────────────────────────────────────
    # 8. Guardar metadata
    # ─────────────────────────────────────────────────────────────
    system_params = {
        "stage_driver": stage_driver,
        "stage_invert_y": bool(w.get("stage_invert_y", False)),
        "trigger_mode": w.get("trigger_mode", "soft_delay"),
        "camera_source": svc.selected.kind if svc.selected else None,
        "spectrometer_driver": spec_cfg.get("driver"),
        "laser_driver": laser_driver,
    }

    mgr.write_system_params(system_params)

    # ─────────────────────────────────────────────────────────────
    # 9. Step0
    # ─────────────────────────────────────────────────────────────
    try:
        step0 = Step0Wizard(
            root,
            run_dir=mgr.session_dir,
            system_params=system_params,
            vc=svc
        )
        step0.run_modal()
    except Exception as e:
        print("WARN Step0:", e)

    # ─────────────────────────────────────────────────────────────
    # 10. Arduino
    # ─────────────────────────────────────────────────────────────
    arduino = None
    if bool(w.get("use_arduino", False)):
        try:
            from service.arduino_service import ArduinoService
            arduino = ArduinoService(
                w.get("arduino_port", "COM3"),
                int(w.get("arduino_baud", 115200))
            )
            arduino.connect()
            print("Arduino OK")
        except Exception as e:
            print("Arduino ERROR:", e)

    # ─────────────────────────────────────────────────────────────
    # 11. Calibración espacial persistente (StageCalibration)
    # ─────────────────────────────────────────────────────────────
    # Carga explícita en el flujo de inicio: queda disponible para el
    # PreviewPanel y para cualquier componente que lo reciba por parámetro.
    # Nota: el pipeline de scan usa x_mm/y_mm pre-calculados del plan;
    # el ScanRunner no necesita la calibración en runtime.
    from service.calibration_service import StageCalibration
    _calib_dir = os.path.join(
        os.path.dirname(os.path.normpath(mgr.session_dir)), "calibrations")
    _cam_label = svc.selected.label if svc.selected else ""
    calibration = StageCalibration.load_persistent(
        _calib_dir, stage_driver, _cam_label)
    if calibration and calibration.valid:
        print("Calibración cargada: n=%d res=%.4f mm" % (
            calibration.n_points, calibration.residual_mm))
    else:
        print("WARN: sin calibración persistente para %s + %s" % (
            stage_driver, _cam_label or "(sin cámara)"))

    # ─────────────────────────────────────────────────────────────
    # 11. Panel
    # ─────────────────────────────────────────────────────────────
    open_control_panel(
        root=root,
        svc=svc,
        session_mgr=mgr,
        stage=stage,
        arduino=arduino,
        params=w,
        laser=laser,
        spectrometer=spectrometer,
        exp_cfg=exp_cfg,
        stage_cam_desc=w.get("stage_cam_desc"),
        calibration=calibration,
    )

    # ─────────────────────────────────────────────────────────────
    # 11. Mainloop
    # ─────────────────────────────────────────────────────────────
    try:
        root.mainloop()
    finally:
        if arduino:
            try: arduino.safe_shutdown()
            except Exception: pass
            try: arduino.disconnect()
            except Exception: pass

        if laser:
            try: laser.disconnect()
            except Exception: pass

        if spectrometer:
            try: spectrometer.set_trigger_mode(0)
            except Exception: pass
            try: time.sleep(0.2)
            except Exception: pass
            try: spectrometer.disconnect()
            except Exception: pass

        try: svc.close()
        except Exception: pass

        if stage:
            try: stage.disconnect()
            except Exception: pass


if __name__ == "__main__":
    main()