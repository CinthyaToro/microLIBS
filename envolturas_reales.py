# -*- coding: utf-8 -*-
"""
envolturas_reales.py — adaptan el hardware real a los contratos.
NO se prueban en la Dell; se completan/prueban en la Asus (labo).
Mientras tanto, el spike corre con los simuladores.
"""
import socket
from capacidades import Firing, Acquiring


class EksplaPorTCP(Firing):
    """Cliente del laser_server.py (Python 32-bit). Esconde el bitness tras el contrato Firing."""

    def __init__(self, host="127.0.0.1", port=27182, timeout_s=5.0):
        self.host, self.port, self.timeout_s = host, port, timeout_s
        self._sock = None

    def conectar(self):
        self._sock = socket.create_connection((self.host, self.port), self.timeout_s)
        self._sock.settimeout(self.timeout_s)

    def _cmd(self, texto):
        self._sock.sendall((texto + "\n").encode())
        resp = self._sock.recv(1024).decode().strip()
        if resp.startswith("ERR"):
            raise RuntimeError("laser_server: " + resp)
        return resp

    def arm(self):
        self._cmd("ARM")                 # server responde ARMED

    def fire_burst(self, n):
        self._cmd("FIRE_BURST %d" % n)   # server ejecuta la secuencia atomica y responde FIRED

    def safe_off(self):
        try:
            self._cmd("SAFE_OFF")
        finally:
            if self._sock:
                self._sock.close()


class OceanReal(Acquiring):
    """Driver del espectrómetro Ocean (SDK 64-bit). Completar con tu SDK (seabreeze/python-seabreeze)."""

    def __init__(self):
        self._dev = None  # TODO: handle del SDK

    def conectar(self):
        # TODO (labo): abrir el dispositivo con tu SDK Ocean
        # from seabreeze.spectrometers import Spectrometer
        # self._dev = Spectrometer.from_first_available()
        raise NotImplementedError("Completar con el SDK del Ocean en el labo")

    def set_trigger_externo(self, activado):
        # TODO: self._dev.trigger_mode(3)  # 3 = external hardware trigger (segun modelo)
        raise NotImplementedError

    def set_ventana_us(self, ventana_us):
        # TODO: self._dev.integration_time_micros(ventana_us)
        raise NotImplementedError

    def armar(self):
        # En muchos Ocean, basta con dejar el trigger externo activo y pedir intensities()
        # que BLOQUEA hasta que llega el trigger. "Armar" = configurar y quedar listo para leer.
        pass

    def leer_espectro(self, timeout_s):
        # TODO: wl = self._dev.wavelengths(); inten = self._dev.intensities()
        # (intensities bloquea hasta el trigger; manejar timeout segun SDK)
        raise NotImplementedError
