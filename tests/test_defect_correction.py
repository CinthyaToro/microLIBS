# -*- coding: utf-8 -*-
"""
tests/test_defect_correction.py
================================
Tests unitarios de DefectCorrector. Sin hardware ni OpenCV.
"""
import json
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from hal.defect_correction import DefectCorrector

W, H = 1280, 960

DEFECT_MAP = {
    "schema_version": 1,
    "camera_model": "CMLN-13S2M",
    "camera_serial": "11470397",
    "reference_dims": {"width": W, "height": H},
    "notes": "Mapa de prueba",
    "interpolate": {
        "columns": [
            {"x_start": 662, "x_end": 663, "y_start": 0, "y_end": H - 1},
            {"x_start": 685, "x_end": 688, "y_start": 0, "y_end": H - 1},
        ],
        "clusters": [
            {"cx": 904, "cy": 601, "radius": 6},
            {"cx": 942, "cy": 561, "radius": 6},
        ],
    },
}


@pytest.fixture
def map_file(tmp_path):
    p = tmp_path / "defectmap.json"
    p.write_text(json.dumps(DEFECT_MAP), encoding="utf-8")
    return str(p)


def flat(val=128):
    return np.full((H, W), val, dtype=np.uint8)


# ─── carga ────────────────────────────────────────────────────────────────────

class TestLoad:
    def test_load_without_serial_check(self, map_file):
        dc = DefectCorrector.load(map_file)
        assert dc is not None

    def test_load_with_correct_serial(self, map_file):
        dc = DefectCorrector.load(map_file, camera_serial=11470397)
        assert dc is not None

    def test_load_serial_mismatch_raises(self, map_file):
        with pytest.raises(ValueError, match="serial"):
            DefectCorrector.load(map_file, camera_serial=99999999)


# ─── verificación de integridad ───────────────────────────────────────────────

class TestIntegrity:
    def test_wrong_dims_raises(self, map_file):
        dc = DefectCorrector.load(map_file)
        bad = np.zeros((100, 100), dtype=np.uint8)
        with pytest.raises(ValueError, match="Dimensiones"):
            dc.apply(bad)

    def test_correct_dims_does_not_raise(self, map_file):
        dc = DefectCorrector.load(map_file)
        dc.apply(flat())  # no debe lanzar


# ─── inmutabilidad de entrada ─────────────────────────────────────────────────

class TestImmutability:
    def test_input_not_mutated(self, map_file):
        dc = DefectCorrector.load(map_file)
        img = flat(128)
        img[:, 662] = 0
        original = img.copy()
        dc.apply(img)
        assert np.array_equal(img, original)

    def test_output_same_shape_and_dtype(self, map_file):
        dc = DefectCorrector.load(map_file)
        img = flat(128)
        out = dc.apply(img)
        assert out.shape == img.shape
        assert out.dtype == img.dtype


# ─── corrección de columnas ───────────────────────────────────────────────────

class TestColumnCorrection:
    def test_defect_cols_replaced_by_neighbor_median(self, map_file):
        dc = DefectCorrector.load(map_file)
        img = flat(100)
        # Columnas defectuosas marcadas con 0
        img[:, 662:664] = 0   # rango 662-663
        img[:, 685:689] = 0   # rango 685-688
        out = dc.apply(img)
        # Los vecinos son 100 en ambos lados → mediana = 100
        assert np.all(out[:, 662:664] == 100), "rango 662-663 no corregido"
        assert np.all(out[:, 685:689] == 100), "rango 685-688 no corregido"

    def test_neighbors_read_from_original_not_propagated(self, map_file):
        """Las columnas del mismo rango no se contaminan entre sí."""
        dc = DefectCorrector.load(map_file)
        img = flat(200)
        img[:, 685:689] = 0
        # vecino izq=200 (col 684), vecino der=200 (col 689) → corregido a 200
        out = dc.apply(img)
        assert np.all(out[:, 685:689] == 200)

    def test_good_columns_unchanged(self, map_file):
        dc = DefectCorrector.load(map_file)
        img = flat(77)
        out = dc.apply(img)
        assert np.all(out[:, 0:662] == 77)
        assert np.all(out[:, 664:685] == 77)
        assert np.all(out[:, 689:] == 77)

    def test_asymmetric_neighbor_values_yield_median(self, map_file):
        """Con vecinos de valores distintos la columna corregida toma la mediana."""
        dc = DefectCorrector.load(map_file)
        img = flat(0)
        img[:, 661] = 100   # vecino izquierdo del primer rango
        img[:, 664] = 200   # vecino derecho del primer rango
        out = dc.apply(img)
        # mediana(100, 200) = 150
        assert np.all(out[:, 662:664] == 150)


# ─── corrección de clusters ───────────────────────────────────────────────────

class TestClusterCorrection:
    def test_cluster_pixels_replaced(self, map_file):
        dc = DefectCorrector.load(map_file)
        img = flat(200)
        cx, cy, r = 904, 601, 6
        ys_g, xs_g = np.mgrid[0:H, 0:W]
        circle = np.sqrt((xs_g - cx) ** 2 + (ys_g - cy) ** 2) <= r
        img[circle] = 0
        out = dc.apply(img)
        assert np.all(out[circle] == 200)

    def test_pixels_outside_cluster_unchanged(self, map_file):
        dc = DefectCorrector.load(map_file)
        img = flat(128)
        out = dc.apply(img)
        cx, cy, r = 904, 601, 6
        ys_g, xs_g = np.mgrid[0:H, 0:W]
        outside = np.sqrt((xs_g - cx) ** 2 + (ys_g - cy) ** 2) > r + 2
        assert np.all(out[outside] == 128)
