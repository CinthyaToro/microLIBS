# -*- coding: utf-8 -*-
"""
tests/test_shutdown_sequence.py
================================
Verifica el CONTRATO de orquestación del apagado de microLIBS.

Este archivo prueba el ORDEN y la ESPERA. Qué le hace cada driver a su
instrumento se prueba en tests/test_driver_safe_shutdown.py.

── Por qué los dobles son autospec ──────────────────────────────────────────
La primera versión de estos tests usaba dobles con `__getattr__`, que
respondían a CUALQUIER método. Eso los volvía inútiles para detectar el peor
bug que tenía este código: el orquestador llamaba a
`cancel_pending_acquisition()`, un método que no existía en ningún driver, y
el test lo daba por bueno porque el doble contestaba igual.

Ahora los dobles se construyen con `create_autospec` sobre las `Base*`: si el
orquestador llama a algo que no está en el contrato, el test revienta con
AttributeError en vez de pasar sobre una ficción.
"""
import threading
from unittest.mock import create_autospec

import pytest

from hal.base_camera import BaseCamera
from hal.base_laser import BaseLaser
from hal.base_spectrometer import BaseSpectrometer
from hal.base_stage import BaseStage
from service import shutdown_service
from service.shutdown_service import ShutdownSequence


# ── Dobles restringidos al contrato ────────────────────────────────────────

def _doble(bitacora, rol, base, falla=False, cuelga=None):
    """
    Instrumento falso limitado a los métodos de su Base.

    falla  -> safe_shutdown() lanza
    cuelga -> Event; safe_shutdown() espera hasta que se active (simula un
              instrumento que no responde)
    """
    m = create_autospec(base, instance=True)

    def _apagarse():
        bitacora.append(rol)
        if cuelga is not None:
            cuelga.wait()
        if falla:
            raise RuntimeError("falla simulada en %s" % rol)

    m.safe_shutdown.side_effect = _apagarse
    return m


class _Runner:
    """El ScanRunner no tiene Base; se lo representa a mano."""
    _thread = None

    def __init__(self, bitacora, falla=False):
        self._b = bitacora
        self._falla = falla

    def stop(self):
        self._b.append("runner.stop")
        if self._falla:
            raise RuntimeError("falla simulada en runner.stop")

    def join(self, timeout=None):
        self._b.append("runner.join")


class _Vision:
    """VisionService: dueño de la cámara, delega en el driver."""
    def __init__(self, bitacora):
        self._b = bitacora

    def safe_shutdown(self):
        self._b.append("camara")


@pytest.fixture
def equipo():
    b = []
    return b, {
        "runner":       _Runner(b),
        "spectrometer": _doble(b, "espectrometro", BaseSpectrometer),
        "laser":        _doble(b, "laser",         BaseLaser),
        "stage":        _doble(b, "platina",       BaseStage),
        "vision":       _Vision(b),
        "arduino":      _doble(b, "arduino",       BaseCamera),
    }


# ── El contrato de orquestación ────────────────────────────────────────────

def test_orden_por_rol(equipo):
    """
    CONTRATO: ScanRunner → espectrómetro → láser → platina → cámara → Arduino.

    El espectrómetro primero para soltarle el latch del USB; el láser antes
    que la platina para que nada se mueva con el equipo armado.
    """
    bitacora, instr = equipo
    ShutdownSequence().run(**instr)

    assert bitacora == [
        "runner.stop", "runner.join",
        "espectrometro", "laser", "platina", "camara", "arduino",
    ]


def test_el_orquestador_no_conoce_marcas():
    """
    R2: esta capa decide el ORDEN, no QUÉ hacerle a cada instrumento.

    Se verifica sobre el código, no sobre la intención: el único método que
    puede llamarle a un instrumento es safe_shutdown(). Si alguien vuelve a
    meter acá set_trigger_mode(), disarm() o los registros del NL230, este
    test se pone rojo.
    """
    import ast
    import inspect

    fuente = inspect.getsource(ShutdownSequence.run)
    arbol = ast.parse(fuente.lstrip())

    # Solo interesa QUÉ se le pide a un INSTRUMENTO. Lo que se haga con
    # threading, listas o self es mecánica interna y no viene al caso.
    instrumentos = {"instrumento", "spectrometer", "laser", "stage",
                    "vision", "arduino"}
    permitidos = {"safe_shutdown"}

    prohibidos = []
    for n in ast.walk(arbol):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        receptor = getattr(n.func.value, "id", None)
        if receptor in instrumentos and n.func.attr not in permitidos:
            prohibidos.append("%s.%s" % (receptor, n.func.attr))

    assert not prohibidos, (
        "el orquestador le esta pidiendo cosas de marca a los instrumentos: %s"
        % sorted(set(prohibidos))
    )


def test_un_instrumento_que_falla_no_bloquea_a_los_demas(equipo):
    """CONTRATO: cada apagado va aislado; un equipo roto no toma a los otros."""
    bitacora, instr = equipo
    instr["laser"] = _doble(bitacora, "laser", BaseLaser, falla=True)

    reporte = ShutdownSequence().run(**instr)

    assert "platina" in bitacora and "camara" in bitacora and "arduino" in bitacora
    assert any(rol == "laser" for rol, _ in reporte["errores"])


def test_un_instrumento_que_NO_RESPONDE_no_cuelga_el_cierre(equipo, monkeypatch):
    """
    CONTRATO: el que no responde tiene techo de espera.

    Es el caso real que motivó esto: cerrar el programa con una adquisición
    del Ocean bloqueada esperando el TTL dejaba la ventana congelada. Ahora
    se lo espera un rato, se avisa, y se sigue.
    """
    monkeypatch.setattr(shutdown_service, "ESPERA_ESPECTROMETRO_S", 0.2)

    bitacora, instr = equipo
    trabado = threading.Event()
    instr["spectrometer"] = _doble(bitacora, "espectrometro",
                                   BaseSpectrometer, cuelga=trabado)

    try:
        reporte = ShutdownSequence().run(**instr)

        # el cierre siguió igual
        assert "laser" in bitacora and "arduino" in bitacora
        # y quedó dicho cuál no respondió
        assert reporte["colgados"] == ["espectrometro"]
        assert any("no respondio" in motivo for _rol, motivo in reporte["errores"])
    finally:
        trabado.set()   # liberar el hilo para no dejarlo colgado


def test_avisa_al_operador_cuando_algo_no_respondio(equipo, monkeypatch):
    """
    El operador tiene que enterarse de que un instrumento pudo quedar tomado:
    ese es el precio que se aceptó a cambio de no colgar el cierre.
    """
    monkeypatch.setattr(shutdown_service, "ESPERA_ESPECTROMETRO_S", 0.2)

    bitacora, instr = equipo
    trabado = threading.Event()
    instr["spectrometer"] = _doble(bitacora, "espectrometro",
                                   BaseSpectrometer, cuelga=trabado)
    lineas = []

    try:
        ShutdownSequence(log=lineas.append).run(**instr)
        assert any("NO RESPONDIO" in l for l in lineas)
        assert any("sin cerrar del todo" in l for l in lineas)
    finally:
        trabado.set()


def test_nunca_lanza(equipo):
    """
    CONTRATO: run() nunca lanza. Se la llama al cerrar la ventana; una
    excepción ahí dejaría el proceso a medio apagar.
    """
    bitacora, instr = equipo
    instr["runner"] = _Runner(bitacora, falla=True)
    for clave, base in (("spectrometer", BaseSpectrometer), ("laser", BaseLaser),
                        ("stage", BaseStage), ("arduino", BaseCamera)):
        instr[clave] = _doble(bitacora, clave, base, falla=True)

    reporte = ShutdownSequence().run(**instr)

    assert reporte["ya_estaba"] is False
    assert reporte["errores"]


def test_es_idempotente(equipo):
    """
    CONTRATO: cerrar dos veces (tecla Escape + botón de la ventana) no puede
    apagar los instrumentos dos veces.
    """
    bitacora, instr = equipo
    seq = ShutdownSequence()

    primero = seq.run(**instr)
    cuantas = len(bitacora)
    segundo = seq.run(**instr)

    assert primero["ya_estaba"] is False
    assert segundo["ya_estaba"] is True
    assert len(bitacora) == cuantas


def test_los_instrumentos_ausentes_se_saltean():
    """
    CONTRATO: un instrumento en None se saltea. El sistema tiene que poder
    cerrar corriendo sin láser, sin espectrómetro o sin platina.
    """
    bitacora = []
    reporte = ShutdownSequence().run(
        runner=None, spectrometer=None, laser=None,
        stage=None, arduino=None, vision=_Vision(bitacora),
    )

    assert reporte["pasos"] == ["camara"]
    assert reporte["errores"] == []
    assert bitacora == ["camara"]


def test_el_log_es_opcional(equipo):
    """Sin callback la secuencia corre igual (uso fuera de la UI)."""
    _b, instr = equipo
    assert ShutdownSequence().run(**instr)["ya_estaba"] is False


def test_el_log_reporta_cada_instrumento(equipo):
    """Con callback, la UI recibe una línea por instrumento."""
    _b, instr = equipo
    lineas = []

    ShutdownSequence(log=lineas.append).run(**instr)

    assert any("Salida segura" in l for l in lineas)
    for rol in ("espectrometro", "laser", "platina", "camara"):
        assert any(rol in l and "cerrado OK" in l for l in lineas), rol
