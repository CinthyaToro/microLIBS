# microLIBS

Sistema de mapeo elemental por LIBS de microplásticos. Mueve una muestra, toma
micrografías, dispara un láser y adquiere el espectro del plasma punto a punto.

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -q      # esperado: 101 passed, 1 skipped
```

Eso alcanza para el modo simulado y los tests, sin ningún instrumento
conectado. Los drivers de hardware se instalan aparte, uno por instrumento.

**Ver [INSTALL.md](INSTALL.md)** para los extras por instrumento, la versión de
Python recomendada y qué hacer si la instalación falla.

## Documentación

| | |
|---|---|
| [INSTALL.md](INSTALL.md) | instalación, verificada en entorno limpio |

> **Nota.** Este repositorio publica, por ahora, el código del sistema y lo necesario
> para ejecutarlo y verificarlo. La documentación del desarrollo —manuales de operación,
> diccionario de la estructura de trabajo, diagnósticos de arquitectura y bitácora— se
> incorpora en una segunda entrega.

---
