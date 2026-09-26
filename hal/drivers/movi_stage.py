# -*- coding: utf-8 -*-
"""
hal/drivers/movi_stage.py
Driver para el sistema MoVi (protocolo serial G-code-like).
Ejes: X, Y únicamente.
Parámetros de connect(): {"port": "COM4", "baud": 115200, "timeout": 5.0}

NUEVO: detección automática de puerto:
    find_movi_port()    → escanea todos los puertos y retorna el que responde como MoVi
    list_serial_ports() → lista todos los puertos serie disponibles

Protocolo de detección:
    MoVi responde "listo para el siguiente comando" DESPUÉS de ejecutar
    un G-code válido. La detección envía "G01 X0" (mover a X=0 micrones,
    no-op si ya está en cero) y espera esa respuesta.
    Si no responde al G01, también acepta cualquier respuesta que contenga
    "listo" o "ready" (por firmware alternativo).
"""
import time
from hal.base_stage import BaseStage


# ─── Detección automática de puerto ──────────────────────────────────────────

def list_serial_ports() -> list:
    """
    Retorna lista de strings con todos los puertos serie disponibles.
    Ejemplo: ["COM3  (USB Serial Device)", "COM4  (CH340)"]  (Windows)
             ["/dev/ttyUSB0", "/dev/ttyACM0"]                (Linux)
    """
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        result = []
        for p in sorted(ports, key=lambda x: x.device):
            desc = (p.description or "").strip()
            if desc and desc != p.device:
                result.append("%s  (%s)" % (p.device, desc))
            else:
                result.append(p.device)
        return result
    except Exception:
        return []


def find_movi_port(timeout_per_port: float = 3.0, log_fn=None) -> str:
    """
    Escanea todos los puertos serie disponibles buscando el stage MoVi.

    Estrategia de detección:
      1. Abre cada puerto a 115200 baud.
      2. Espera 2 s para que el firmware inicialice (importante en Windows
         donde los adaptadores CH340/CP210x pueden tardar).
      3. Envía "G01 X0\\n" → MoVi ejecuta move a X=0 (no-op si ya está ahí)
         y responde "listo para el siguiente comando".
      4. Si no hay respuesta al G01, prueba "\\n" como segunda opción.

    Parámetros:
        timeout_per_port  Tiempo máximo de espera por puerto (segundos).
        log_fn            Función opcional log_fn(str) para mostrar progreso.

    Retorna:
        El string del puerto (ej. "COM4") si encontró MoVi, o "" si no.
    """
    try:
        import serial
        import serial.tools.list_ports
    except ImportError:
        if log_fn:
            log_fn("Error: pyserial no está instalado. Ejecutá: pip install pyserial")
        return ""

    try:
        raw_ports = list(serial.tools.list_ports.comports())
    except Exception as e:
        if log_fn:
            log_fn("Error listando puertos: %s" % e)
        return ""

    devices = [p.device for p in sorted(raw_ports, key=lambda x: x.device)]

    if not devices:
        if log_fn:
            log_fn("No se encontraron puertos serie en el sistema.")
        return ""

    if log_fn:
        log_fn("Puertos disponibles: %s" % ", ".join(devices))
        log_fn("Buscando MoVi (G01 X0 → 'listo')...")

    # Comandos de prueba en orden de preferencia
    # G01 X0 = mover a X=0 micrones (no-op si ya está ahí)
    # \n solo = algunos firmwares responden igual
    PROBE_CMDS = [b"G01 X0\n", b"\n"]
    READY_KW   = "listo"

    for port in devices:
        if log_fn:
            log_fn("Probando %s ..." % port)
        ser = None
        try:
            ser = serial.Serial(
                port=port,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout_per_port,
                write_timeout=2.0,
            )

            # Esperar a que el adaptador y el firmware estén listos
            # Windows con CH340/CP210x necesita ~2 s para estabilizar
            time.sleep(2.0)

            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except Exception:
                pass

            found = False
            for cmd in PROBE_CMDS:
                # Limpiar buffer antes de cada intento
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass

                try:
                    ser.write(cmd)
                    ser.flush()
                except Exception as e:
                    if log_fn:
                        log_fn("  %s: error al escribir: %s" % (port, e))
                    break

                t0 = time.time()
                while time.time() - t0 < timeout_per_port:
                    try:
                        raw = ser.readline()
                    except Exception:
                        break
                    if not raw:
                        continue
                    text = raw.decode("utf-8", "ignore").strip().lower()
                    if not text:
                        continue
                    if log_fn:
                        log_fn("  %s → '%s'" % (port, text[:70]))
                    if READY_KW in text or "ready" in text:
                        found = True
                        break

                if found:
                    break

            ser.close()

            if found:
                if log_fn:
                    log_fn("✅ MoVi encontrado en %s" % port)
                return port
            else:
                if log_fn:
                    log_fn("  %s: sin respuesta MoVi." % port)

        except serial.SerialException as e:
            if log_fn:
                log_fn("  %s: no disponible (%s)" % (port, e))
        except Exception as e:
            if log_fn:
                log_fn("  %s: error (%s)" % (port, e))
        finally:
            try:
                if ser and ser.is_open:
                    ser.close()
            except Exception:
                pass

    if log_fn:
        log_fn("❌ MoVi no encontrado en ningún puerto.")
    return ""


# ─── Driver MoVi ─────────────────────────────────────────────────────────────

class MoviStage(BaseStage):
    """
    Driver para stage MoVi con protocolo G-code serial.
    Ejes X e Y. Sin encoder ni fines de carrera.
    Posición gestionada por software (comandada).
    """

    AXES = ("x", "y")
    READY_KEYWORD = "listo para el siguiente comando"

    def __init__(self):
        self._ser     = None
        self._port    = None
        self._baud    = 115200
        self._timeout = 5.0
        self._pos     = {"x": 0.0, "y": 0.0}

    def connect(self, params: dict) -> None:
        import serial
        self._port    = params.get("port", "COM4")
        self._baud    = int(params.get("baud", 115200))
        self._timeout = float(params.get("timeout", 5.0))
        self._ser = serial.Serial(
            self._port, self._baud, timeout=self._timeout)
        time.sleep(2.0)
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass
        print("MoviStage: conectado a %s @ %d." % (self._port, self._baud))

    def disconnect(self) -> None:
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        except Exception:
            pass
        self._ser = None
        print("MoviStage: desconectado.")

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def has_homing(self, axis: str) -> bool:
        return False

    def home(self, axis: str) -> None:
        ax = axis.lower()
        if ax not in self.AXES:
            return
        self.move_abs(ax, 0.0)
        self._pos[ax] = 0.0

    def move_abs(self, axis: str, pos_mm: float) -> None:
        ax = axis.lower()
        if ax not in self.AXES:
            raise ValueError(
                "MoviStage: eje '%s' no soportado (solo x, y)." % axis)
        microns = int(round(pos_mm * 1000))
        self._send("G01 %s%d" % (ax.upper(), microns))
        self._pos[ax] = pos_mm

    def move_rel(self, axis: str, delta_mm: float) -> None:
        ax = axis.lower()
        self.move_abs(ax, self._pos.get(ax, 0.0) + delta_mm)

    def stop(self, axis: str) -> None:
        print("MoviStage: STOP %s (no soportado en firmware MoVi)." % axis)

    def position(self, axis: str) -> float:
        ax = axis.lower()
        if ax not in self.AXES:
            raise ValueError("MoviStage: eje '%s' no existe." % axis)
        return self._pos.get(ax, 0.0)

    def _send(self, cmd: str) -> str:
        if not self.is_connected:
            raise RuntimeError("MoviStage: no conectado.")
        self._ser.write((cmd.strip() + "\n").encode("ascii", "ignore"))
        self._ser.flush()
        t0 = time.time()
        while time.time() - t0 < self._timeout:
            try:
                raw = self._ser.readline()
            except Exception:
                break
            if not raw:
                continue
            text = raw.decode("utf-8", "ignore").strip()
            if not text:
                continue
            if self.READY_KEYWORD in text.lower():
                return text
            if "err" in text.lower():
                raise RuntimeError(
                    "MoviStage: error '%s': %s" % (cmd, text))
        raise TimeoutError(
            "MoviStage: timeout (%.1fs) esperando respuesta a '%s'."
            % (self._timeout, cmd))

    # ── Apagado seguro ──────────────────────────────────────────────────────
    # Segundos de espera por eje al homear en el apagado. El home de este
    # hardware puede colgarse, asi que cada eje va en su hilo con limite:
    # el cierre del sistema no puede quedar tomado por una platina trabada.
    ESPERA_HOME_EJE_S = 30.0

    def safe_shutdown(self) -> None:
        """
        Apagado seguro: llevar x e y a home (con limite de tiempo por eje) y
        desconectar. Ver BaseStage.
        """
        import threading as _threading

        def _home(ax):
            try:
                self.home(ax)
            except Exception:
                pass

        for _ax in ("x", "y"):
            _th = _threading.Thread(target=_home, args=(_ax,), daemon=True)
            _th.start()
            _th.join(self.ESPERA_HOME_EJE_S)
        self.disconnect()
