# Instalación de microLIBS

Todo lo que dice este archivo fue verificado en entornos limpios el 22-Sep-2026.

---

## 1 · Instalación mínima (sin hardware)

Sirve para desarrollar, revisar código, correr los tests y usar el modo
simulado. **No necesita ningún instrumento conectado.**

```bash
git clone https://github.com/CinthyaToro/microLIBS.git
cd microLIBS
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -q
```

Resultado esperado: **`101 passed, 1 skipped`**.

Si eso pasa, la instalación está bien. El `skipped` es a propósito: es el
golden run de v2.1, jubilado — el test explica el motivo si lo mirás.

### Versión de Python

| Versión | Estado |
|---|---|
| **3.12** | recomendada. Verificado: 101 passed |
| 3.9 | funciona, pero **sin soporte desde octubre de 2025** |

En Windows, ojo con cuál lanzás: `python` y `py` pueden apuntar a
intérpretes distintos en la misma máquina. Verificá con `python -V` **después**
de activar el venv.

---

## 2 · Agregar instrumentos

Instalá **solo** los extras de los instrumentos que tengas conectados en esa PC.

```bash
pip install -r requirements-ocean.txt      # espectrómetro Ocean HR2000+
pip install -r requirements-thorlabs.txt   # platina Thorlabs Kinesis
pip install -r requirements-windows.txt    # enumerar cámaras USB, puerto serie
```

Cada uno de esos archivos dice qué **además** hay que instalar por fuera de pip
(SDK de Thorlabs, driver WinUSB con Zadig, etc.).

### La cámara FLIR Chameleon es un caso aparte

En esa PC, **usá la instalación offline**, desde el wheel versionado en el repo:

```bash
pip install --no-index --find-links wheels pyflycap2==0.3.1
```

Así no depende de PyPI ni de la red, y no puede cambiar con el tiempo. El
archivo es `wheels/pyflycap2-0.3.1-cp39-cp39-win_amd64.whl` y su sha256 está
anotado en `requirements-chameleon.txt`.

`pyflycap2` **solo instala en Python 3.9** (no hay wheel para versiones más
nuevas; intenta compilar desde fuente y falla). Además necesita el SDK
FlyCapture2 instalado aparte.

Si esa PC no tiene la Chameleon conectada, **no instales este extra**.

---

## 3 · Si la instalación falla

### `pip install -r requirements.txt` no instala nada

Antes del 22-Sep-2026 `pyflycap2` estaba en el requirements principal. Cuando
un paquete falla, **pip aborta el comando entero y no instala nada** — ni
numpy. Si estás en un clon viejo, actualizá:

```bash
git pull
```

### El error menciona `build_ext`, `Cython` o `FlyCapture`

Estás instalando el extra de la Chameleon en un Python sin wheel. O usás
Python 3.9 para esa PC, o no instales ese extra.

---

## 4 · Correr el sistema

```bash
python main.py config/sim_iberolibs.yaml     # todo simulado
python main.py config/lab_iberolibs.yaml     # laboratorio, hardware real
```

Los manuales de operación se publican en una segunda entrega de este repositorio.

Para el láser EKSPLA hace falta además `laser_server.py` corriendo en un
**Python de 32 bits** aparte (la DLL del láser es de 32 bits y el resto del
sistema es de 64). Se comunican por TCP en `127.0.0.1:27182`.

---

## 5 · Qué NO viaja en el `git clone`

Estos hay que instalarlos a mano en cada PC con hardware:

| | |
|---|---|
| SDK FlyCapture2 | cámara Chameleon |
| Thorlabs Kinesis SDK + .NET Framework | platina |
| Driver WinUSB por Zadig, en cada módulo HR2000+ | espectrómetro |
| Python de 32 bits + DLL de REMOTECONTROL | láser EKSPLA |
