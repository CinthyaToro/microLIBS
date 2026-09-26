# -*- coding: utf-8 -*-
"""
application/profiles_manager.py

Gestión de perfiles del instrumento (instrument_profile.json).
Los perfiles representan la "mejor configuración" del hardware (delay, integración, etc.)
y se seleccionan/guardan en el Paso 0.

Diseñado para transferibilidad: archivo JSON autocontenido.
"""
from __future__ import annotations
import json, os, time
from typing import Dict, Optional

def now_tag() -> str:
    return time.strftime("%Y%m%d_%H%M%S")

class ProfilesManager:
    def __init__(self, profiles_dir: str):
        self.profiles_dir=os.path.abspath(profiles_dir)
        os.makedirs(self.profiles_dir, exist_ok=True)

    def list_profiles(self):
        out=[]
        for fn in os.listdir(self.profiles_dir):
            if fn.lower().endswith(".json"):
                out.append(fn)
        return sorted(out)

    def load(self, filename: str) -> Dict:
        p=os.path.join(self.profiles_dir, filename)
        with open(p,"r",encoding="utf-8") as f:
            return json.load(f)

    def save(self, profile: Dict, filename: Optional[str]=None) -> str:
        if not filename:
            filename=f"instrument_profile_{now_tag()}.json"
        p=os.path.join(self.profiles_dir, filename)
        with open(p,"w",encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        return p
