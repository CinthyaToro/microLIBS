import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

# scan_service.py imprime emojis/unicode (▶ ✅ ⚠️) con print().
# En Windows con cp1252 esto mata el hilo del ScanRunner. Forzar UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
