# -*- coding: utf-8 -*-
"""
simuladores.py — gemelos simulados (R9). Cumplen los MISMOS contratos.
Permiten correr el spike completo en la Dell SIN laboratorio.
"""
import math
import random
import time

from capacidades import Firing, Acquiring


class SimLaser(Firing):
    def __init__(self):
        self._armado = False
        self.disparos = 0

    def arm(self):
        self._armado = True
        print("[sim-laser] armado")

    def fire_burst(self, n):
        if not self._armado:
            raise RuntimeError("fire_burst sin arm() previo")
        time.sleep(0.05)
        self.disparos += n
        print(f"[sim-laser] fire_burst({n}) -> SYNC OUT TTL (simulado)")

    def safe_off(self):
        self._armado = False
        print("[sim-laser] output OFF (seguro)")


class SimSpectro(Acquiring):
    """Devuelve un espectro de prueba con un par de 'líneas' gaussianas + ruido."""

    def __init__(self):
        self._trig = False
        self._ventana_us = 1000
        self._armado = False

    def set_trigger_externo(self, activado):
        self._trig = activado
        print(f"[sim-ocean] trigger externo = {activado}")

    def set_ventana_us(self, ventana_us):
        self._ventana_us = ventana_us
        print(f"[sim-ocean] ventana = {ventana_us} us")

    def armar(self):
        self._armado = True
        print("[sim-ocean] armado: esperando trigger")

    def leer_espectro(self, timeout_s):
        if not self._armado:
            raise RuntimeError("leer_espectro sin armar()")
        # Espectro sintético 200-900 nm
        wl = [200 + i for i in range(701)]
        inten = []
        for x in wl:
            fondo = 50 + random.gauss(0, 3)
            linea1 = 800 * math.exp(-((x - 589) ** 2) / (2 * 4 ** 2))   # ~Na
            linea2 = 500 * math.exp(-((x - 393) ** 2) / (2 * 3 ** 2))   # ~Ca
            inten.append(fondo + linea1 + linea2)
        self._armado = False
        print("[sim-ocean] espectro leido (simulado)")
        return wl, inten
