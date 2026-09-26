# -*- coding: utf-8 -*-
"""
tests/test_driver_safe_shutdown.py
===================================
Cada instrumento sabe apagarse solo.

Antes del 22-Sep-2026 la receta de apagado de cada instrumento vivía en el
orquestador, que conocía marcas y modelos: los registros del NL230, el modo
trigger del Ocean. Eso incumplía R2 (por capacidad, no por marca) y tenía una
consecuencia concreta: el orquestador llamaba a `cancel_pending_acquisition()`,
un método que **no existía en ningún driver**, y el `try/except` tapaba el
`AttributeError`. Ese paso del "contrato crítico" nunca se ejecutó.

Ahora la receta vive en cada driver, detrás de `safe_shutdown()`, declarado
abstracto en las cuatro `Base*`. Estos tests verifican las dos mitades:

  1. ESTRUCTURA: un driver no puede existir sin declarar cómo se apaga.
  2. RECETA: cada driver hace efectivamente lo que su instrumento necesita.
"""
import ast
import glob
import inspect

import pytest

from hal.base_camera import BaseCamera
from hal.base_laser import BaseLaser
from hal.base_spectrometer import BaseSpectrometer
from hal.base_stage import BaseStage


# ── 1. Estructura: nadie se puede olvidar ──────────────────────────────────

@pytest.mark.parametrize("base", [BaseCamera, BaseLaser, BaseStage, BaseSpectrometer])
def test_las_cuatro_bases_lo_exigen(base):
    """
    `safe_shutdown` es abstracto en las cuatro bases. Esto es lo que hace que
    la coherencia sea estructural y no algo que haya que acordarse: si mañana
    se suma un quinto instrumento, el lenguaje obliga a declarar su apagado.
    """
    assert "safe_shutdown" in base.__abstractmethods__


def test_un_driver_que_se_olvida_no_se_puede_instanciar():
    """
    Y falla al CONSTRUIRLO, en hal/factory.py — no en silencio a la hora de
    apagar, que es cuando ya no hay nadie mirando.
    """
    class LaserIncompleto(BaseLaser):
        def connect(self, params): pass
        def disconnect(self): pass
        @property
        def is_connected(self): return False
        def fire(self, pulse_us, delay_us=0): return {}
        def arm(self): pass
        def disarm(self): pass
        def fire_burst(self, n_pulsos): return {}
        @property
        def rep_rate_hz(self): return 10.0

    with pytest.raises(TypeError, match="safe_shutdown"):
        LaserIncompleto()


def test_todos_los_drivers_del_repo_la_implementan():
    """
    Recorre hal/drivers/ y verifica que cada clase que hereda de una Base
    declare safe_shutdown en su propio cuerpo — no heredada.

    Se hace por AST y no importando, para que no dependa de tener los SDK
    de hardware instalados.
    """
    bases = {"BaseCamera", "BaseLaser", "BaseStage", "BaseSpectrometer"}
    faltan = []
    revisados = 0

    for ruta in sorted(glob.glob("hal/drivers/*.py")):
        arbol = ast.parse(open(ruta, encoding="utf-8").read())
        for nodo in arbol.body:
            if not isinstance(nodo, ast.ClassDef):
                continue
            hereda = {getattr(b, "id", getattr(b, "attr", "")) for b in nodo.bases}
            if not (hereda & bases):
                continue
            revisados += 1
            metodos = {m.name for m in nodo.body if isinstance(m, ast.FunctionDef)}
            if "safe_shutdown" not in metodos:
                faltan.append("%s (%s)" % (nodo.name, ruta))

    assert revisados >= 10, "esperaba al menos 10 drivers, encontre %d" % revisados
    assert not faltan, "drivers sin safe_shutdown: %s" % faltan


# ── 2. Recetas: cada uno hace lo suyo ──────────────────────────────────────

class _Espia:
    """Mixin que anota las llamadas en vez de ejecutarlas."""

    def _anotar(self, que):
        self.bitacora.append(que)


def _espiar(cls, metodos):
    """Crea una subclase del driver que registra las llamadas indicadas."""
    cuerpo = {"bitacora": None}

    def hacer(nombre):
        def _m(self, *a, **k):
            self.bitacora.append(nombre)
        return _m

    for m in metodos:
        cuerpo[m] = hacer(m)

    def __init__(self, *a, **k):
        cls.__init__(self, *a, **k)
        self.bitacora = []

    cuerpo["__init__"] = __init__
    return type("Espia" + cls.__name__, (cls,), cuerpo)


def test_receta_del_laser():
    """
    EKSPLA NL230: desarmar, dejar los 4 registros en estado seguro, y recién
    ahí desconectar. Si se desconectara antes, el equipo podría quedar armado.
    """
    from hal.drivers.sim_laser import SimLaser
    Espia = _espiar(SimLaser, ["disarm", "set_register", "disconnect"])

    laser = Espia()
    laser.safe_shutdown()

    assert laser.bitacora[0] == "disarm"
    assert laser.bitacora[-1] == "disconnect"
    assert laser.bitacora.count("set_register") == 4


def test_receta_del_espectrometro():
    """
    HR2000+: salir del modo trigger ANTES de cerrar. Al revés se arriesga
    errno 10060 / freeze del USB.
    """
    from hal.drivers.sim_spectrometer import SimSpectrometer
    Espia = _espiar(SimSpectrometer, ["set_trigger_mode", "disconnect"])

    spec = Espia()
    spec.safe_shutdown()

    assert spec.bitacora == ["set_trigger_mode", "disconnect"]


def test_receta_de_la_platina():
    """Platina: llevar x e y a home antes de desconectar."""
    from hal.drivers.sim_stage import SimStage
    Espia = _espiar(SimStage, ["home", "disconnect"])

    stage = Espia()
    stage.safe_shutdown()

    assert stage.bitacora == ["home", "home", "disconnect"]


def test_receta_de_la_camara():
    """Cámara: detener la captura antes de cerrar."""
    from hal.drivers.sim_camera import SimCamera
    Espia = _espiar(SimCamera, ["stop_capture", "close"])

    cam = Espia()
    cam.safe_shutdown()

    assert cam.bitacora == ["stop_capture", "close"]


# ── 3. El contrato de la Base, sobre los gemelos simulados ─────────────────

def _sims():
    from hal.drivers.sim_camera import SimCamera
    from hal.drivers.sim_laser import SimLaser
    from hal.drivers.sim_spectrometer import SimSpectrometer
    from hal.drivers.sim_stage import SimStage
    return [SimCamera, SimLaser, SimSpectrometer, SimStage]


@pytest.mark.parametrize("cls", _sims(), ids=lambda c: c.__name__)
def test_es_idempotente(cls):
    """CONTRATO: llamarlo dos veces no rompe nada."""
    inst = cls()
    inst.safe_shutdown()
    inst.safe_shutdown()


@pytest.mark.parametrize("cls", _sims(), ids=lambda c: c.__name__)
def test_no_lanza_en_un_instrumento_recien_creado(cls):
    """
    CONTRATO: apagar algo que nunca se conectó no puede explotar. Pasa de
    verdad: el usuario cierra el programa sin haber conectado el hardware.
    """
    cls().safe_shutdown()


@pytest.mark.parametrize("real,sim", [
    ("hal.drivers.laser_proxy:LaserProxy",              "hal.drivers.sim_laser:SimLaser"),
    ("hal.drivers.ocean_spectrometer:OceanSpectrometer", "hal.drivers.sim_spectrometer:SimSpectrometer"),
])
def test_r9_el_gemelo_hace_la_misma_secuencia(real, sim):
    """
    R9: el gemelo simulado debe hacer la MISMA secuencia que el real, para que
    un test contra el sim signifique algo sobre el hardware.

    Se compara qué métodos llama cada safe_shutdown, no el texto: así el test
    sobrevive a cambios de formato pero detecta si una de las dos ramas suma o
    pierde un paso.
    """
    import importlib

    def llamadas_de(ref):
        mod, clase = ref.split(":")
        cls = getattr(importlib.import_module(mod), clase)
        fuente = inspect.getsource(cls.safe_shutdown)
        arbol = ast.parse(fuente.lstrip())
        vistas = []
        for n in ast.walk(arbol):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                if isinstance(n.func.value, ast.Name) and n.func.value.id == "self":
                    vistas.append(n.func.attr)
        return vistas

    assert llamadas_de(real) == llamadas_de(sim)
