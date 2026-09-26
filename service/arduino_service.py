# -*- coding: utf-8 -*-
"""
service/arduino_service.py
==========================
Comunicación con Arduino firmware eMoli5A_microLIBS.
Comandos: M15 (luz), M14 (disparo), M999 (reset).
"""
from __future__ import annotations
import time
from typing import Optional


class ArduinoService:

    def __init__(self, port: str, baud: int = 115200, timeout_s: float = 2.0):
        self.port = str(port)
        self.baud = int(baud)
        self.timeout_s = float(timeout_s)
        self._ser = None

    def connect(self) -> None:
        import serial
        self._ser = serial.Serial(self.port, self.baud, timeout=0.2)
        time.sleep(2.0)
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass
        print("ArduinoService: conectado a %s @ %d" % (self.port, self.baud))

    def disconnect(self) -> None:
        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass
        self._ser = None

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def send_and_wait(self, line: str, timeout_s: Optional[float] = None) -> dict:
        if not self.is_connected:
            raise RuntimeError("Arduino no conectado.")
        to = float(timeout_s or self.timeout_s)
        cmd = (line.strip() + "\n").encode("ascii", "ignore")
        self._ser.write(cmd)
        self._ser.flush()
        t0 = time.time()
        lines = []
        while time.time() - t0 < to:
            raw = self._ser.readline()
            if not raw:
                continue
            txt = raw.decode("utf-8", "ignore").strip()
            if not txt:
                continue
            lines.append(txt)
            low = txt.lower()
            if low.startswith("ok") or "err" in low:
                break
        return {"cmd": line.strip(), "lines": lines,
                "t_end_iso": time.strftime("%Y-%m-%dT%H:%M:%S")}

    def light(self, on: bool) -> dict:
        return self.send_and_wait("M15 S%d" % (1 if on else 0), timeout_s=1.2)

    def fire(self, pulse_us: int, delay_us: int = 0,
             post_ms: int = 0, soft_trig: int = 1) -> dict:
        cmd = "M14 P%d D%d S%d A%d" % (int(pulse_us), int(delay_us),
                                          int(soft_trig), int(post_ms))
        return self.send_and_wait(cmd, timeout_s=2.5)

    def reset(self) -> dict:
        return self.send_and_wait("M999", timeout_s=1.2)

    def safe_shutdown(self) -> None:
        """
        Apaga luz, resetea salidas y desconecta (no lanza excepciones).

        Cumple el mismo contrato que `safe_shutdown()` de los drivers del HAL
        (ver `hal/base_*.py`): deja el instrumento en estado seguro Y CERRADO.

        El `disconnect()` se agregó el 22-Sep-2026: hasta entonces este método
        no desconectaba, y era el orquestador el que llamaba a `disconnect()`
        aparte. Al unificar el apagado detrás de un solo método, sin esto el
        Arduino habría quedado conectado al cerrar el programa.
        """
        try:
            self.light(False)
        except Exception:
            pass
        try:
            self.reset()
        except Exception:
            pass
        try:
            self.disconnect()
        except Exception:
            pass
