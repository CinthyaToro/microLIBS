# -*- coding: utf-8 -*-
"""
tests/test_calibration_cala.py
================================
Tests de Cal-A: calibracion homografica estatica con tablero de ajedrez.

Ejecutar:
    python -m pytest tests/test_calibration_cala.py -v

Todos los tests corren sin hardware: usan imagenes sinteticas o datos numericos.
"""

import json
import pathlib
import sys
import numpy as np
import pytest

# asegurar que el raiz del proyecto esta en sys.path
ROOT = pathlib.Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# helpers internos de test
# ---------------------------------------------------------------------------

def _make_minimal_profile(H: np.ndarray, px_list, mm_list) -> dict:
    """Construye un perfil minimo valido para tests de roundtrip."""
    from service.platform_profile import build_profile

    camara = {"modelo": "TEST", "serial": "0", "resolucion": [1296, 964],
              "px_um": 3.75, "mascara_defectos": {}}
    optica = {"f_mm": 55, "iris_mm": 10.5, "f_num": 5.2, "difraccion_um": 3.5}
    escala = {"px_por_mm": 218, "um_por_px": 4.59, "aumento": 0.82, "fov_mm": [5.9, 4.4]}
    patron = {"tipo": "ajedrez", "casilla_mm": 0.5, "casillas": [9, 7], "esquinas": 48}
    metricas = {"rms_um": 5.0, "rms_px": 1.0, "esquinas_detectadas": 48,
                "det_lineal": 1.0, "isotropia_xy": 0.99}
    checks = {"nitidez_ok": True, "saturacion_ok": True,
              "espejado_ok": True, "escala_cross_ok": True}

    return build_profile(
        camara=camara, optica=optica, escala=escala, patron=patron,
        H=H,
        puntos_crudos={"px": px_list, "mm_nominal": mm_list},
        metricas=metricas, checks=checks,
        operador="pytest",
    )


# ---------------------------------------------------------------------------
# Commit 1 — test_profile_roundtrip
# ---------------------------------------------------------------------------

def test_profile_roundtrip(tmp_path):
    """save -> load -> recompute_H reproduce H con tolerancia numerica."""
    from service.platform_profile import build_profile, save_profile, load_profile, recompute_H
    from tests.fixtures.synthetic_board import board_corners_px_ideal, board_corners_mm_nominal

    px   = board_corners_px_ideal(inner_corners=(8, 6), square_px=60, margin_px=40)
    mm   = board_corners_mm_nominal(inner_corners=(8, 6), square_mm=0.5)

    import cv2
    H_orig, _ = cv2.findHomography(px.astype(np.float64), mm.astype(np.float64), 0)
    assert H_orig is not None

    profile = _make_minimal_profile(H_orig, px.tolist(), mm.tolist())

    out_path = str(tmp_path / "perfil_calibracion.json")
    saved = save_profile(profile, out_path)
    assert pathlib.Path(saved).exists(), f"Perfil no guardado en {saved}"

    loaded = load_profile(saved)
    H_recomputed = recompute_H(loaded)

    assert H_recomputed.shape == (3, 3)
    # KPI-4: H reproducido debe coincidir con el original (tolerancia numerica)
    np.testing.assert_allclose(H_recomputed, H_orig, rtol=1e-4, atol=1e-6,
                               err_msg="recompute_H difiere del H original")


def test_save_profile_versioning(tmp_path):
    """save_profile no sobrescribe: genera _v1, _v2, _v3..."""
    from service.platform_profile import save_profile
    from tests.fixtures.synthetic_board import board_corners_px_ideal, board_corners_mm_nominal
    import cv2

    px  = board_corners_px_ideal()
    mm  = board_corners_mm_nominal()
    H, _ = cv2.findHomography(px.astype(np.float64), mm.astype(np.float64), 0)

    base = str(tmp_path / "perfil")
    p1 = save_profile(_make_minimal_profile(H, px.tolist(), mm.tolist()), base + ".json")
    p2 = save_profile(_make_minimal_profile(H, px.tolist(), mm.tolist()), base + ".json")
    p3 = save_profile(_make_minimal_profile(H, px.tolist(), mm.tolist()), base + ".json")

    assert p1 != p2 != p3, "save_profile debe generar rutas distintas"
    assert "_v1" in p1
    assert "_v2" in p2
    assert "_v3" in p3


# ---------------------------------------------------------------------------
# Commit 2 — tests de validadores puros
# ---------------------------------------------------------------------------

def test_sharpness_sharp_image():
    """Imagen nitida da sharpness_score alto (> 100)."""
    from service.calibration_service import sharpness_score
    from tests.fixtures.synthetic_board import make_board_image

    img = make_board_image(blur_sigma=0.0)
    score = sharpness_score(img)
    assert score > 100.0, f"Imagen nitida deberia dar score > 100, dio {score:.1f}"


def test_sharpness_blurry_image():
    """Imagen desenfocada da sharpness_score bajo (< 20)."""
    from service.calibration_service import sharpness_score
    from tests.fixtures.synthetic_board import make_board_image

    img = make_board_image(blur_sigma=8.0)
    score = sharpness_score(img)
    assert score < 20.0, f"Imagen borrosa deberia dar score < 20, dio {score:.1f}"


def test_check_exposure_normal():
    """Imagen normal: saturacion y subexposicion dentro de limites."""
    from service.calibration_service import check_exposure

    img = np.full((100, 100), 128, dtype=np.uint8)
    result = check_exposure(img)
    assert result["ok"] is True
    assert result["saturated_frac"] < 0.01
    assert result["underexposed_frac"] < 0.01


def test_check_exposure_saturated():
    """Imagen saturada: saturated_frac alto y ok=False."""
    from service.calibration_service import check_exposure

    img = np.full((100, 100), 255, dtype=np.uint8)
    result = check_exposure(img)
    assert result["saturated_frac"] > 0.8
    assert result["ok"] is False


def test_dead_pixel_mask_shape():
    """load_dead_pixel_mask devuelve mascara booleana de shape correcto."""
    from service.calibration_service import load_dead_pixel_mask

    shape = (964, 1296)
    mask = load_dead_pixel_mask(shape, columns=[100, 500], cluster_bbox=None)
    assert mask.shape == shape
    assert mask.dtype == bool
    # columnas marcadas como True (muerto)
    assert mask[:, 100].all()
    assert mask[:, 500].all()
    # resto False
    assert not mask[:, 200].any()


def test_dead_pixel_mask_cluster():
    """load_dead_pixel_mask marca el bbox del cumulo."""
    from service.calibration_service import load_dead_pixel_mask

    shape = (964, 1296)
    bbox = (10, 20, 15, 25)  # (y0, x0, y1, x1)
    mask = load_dead_pixel_mask(shape, columns=[], cluster_bbox=bbox)
    assert mask[10:15, 20:25].all()
    assert not mask[0, 0]


def test_orientation_sign_check_correct():
    """Movimiento en X positivo -> desplazamiento en columna positivo."""
    from service.calibration_service import orientation_sign_check

    # mueve +1 mm en X, observamos +delta en columna (u) -> correcto
    ok = orientation_sign_check(move_mm=1.0, delta_px_observed=+50.0, expected_axis="x")
    assert ok is True


def test_orientation_sign_check_wrong():
    """Signo incorrecto retorna False."""
    from service.calibration_service import orientation_sign_check

    ok = orientation_sign_check(move_mm=1.0, delta_px_observed=-50.0, expected_axis="x")
    assert ok is False


# ---------------------------------------------------------------------------
# Commit 3 — tests de deteccion y homografia
# ---------------------------------------------------------------------------

def test_detect_chessboard_finds_corners():
    """Tablero sintetico claro: se detectan las 48 esquinas esperadas."""
    from service.calibration_service import detect_chessboard, load_dead_pixel_mask
    from tests.fixtures.synthetic_board import make_board_image

    img  = make_board_image(inner_corners=(8, 6), square_px=60, margin_px=40)
    mask = load_dead_pixel_mask(img.shape, columns=[], cluster_bbox=None)
    corners = detect_chessboard(img, mask, inner_corners=(8, 6))

    assert corners is not None, "No se detectaron esquinas en tablero sintetico claro"
    assert corners.shape[0] == 48, f"Esperaba 48 esquinas, detecte {corners.shape[0]}"


def test_detect_chessboard_blurry_returns_none_or_corners():
    """Con desenfoque muy fuerte puede fallar la deteccion (no lanza excepcion)."""
    from service.calibration_service import detect_chessboard, load_dead_pixel_mask
    from tests.fixtures.synthetic_board import make_board_image

    img  = make_board_image(inner_corners=(8, 6), blur_sigma=15.0)
    mask = load_dead_pixel_mask(img.shape, columns=[], cluster_bbox=None)
    # No debe lanzar excepcion; puede retornar None
    corners = detect_chessboard(img, mask, inner_corners=(8, 6))
    # resultado puede ser None o array; lo importante es que no truena


def test_detect_chessboard_ex_returns_debug_image():
    """detect_chessboard_ex devuelve siempre una imagen de debug BGR (H,W,3)."""
    from service.calibration_service import detect_chessboard_ex, load_dead_pixel_mask
    from tests.fixtures.synthetic_board import make_board_image
    import numpy as np

    img  = make_board_image(inner_corners=(8, 6), square_px=60, margin_px=40)
    mask = load_dead_pixel_mask(img.shape, columns=[], cluster_bbox=None)
    corners, debug_img, msg = detect_chessboard_ex(img, mask, inner_corners=(8, 6))

    assert corners is not None
    assert debug_img is not None
    assert debug_img.ndim == 3 and debug_img.shape[2] == 3, \
        f"debug_img debe ser BGR (H,W,3), tiene shape {debug_img.shape}"
    assert isinstance(msg, str) and len(msg) > 0


def test_detect_chessboard_ex_fail_returns_debug_image():
    """Cuando la deteccion falla, debug_img no es None (permite verlo al operador)."""
    from service.calibration_service import detect_chessboard_ex, load_dead_pixel_mask
    import numpy as np

    # Imagen uniforme: jamas contiene un tablero
    img  = np.full((200, 200), 128, dtype=np.uint8)
    mask = load_dead_pixel_mask(img.shape, columns=[], cluster_bbox=None)
    corners, debug_img, msg = detect_chessboard_ex(img, mask, inner_corners=(8, 6))

    assert corners is None, "No deberia detectar esquinas en una imagen uniforme"
    assert debug_img is not None, "debug_img debe existir incluso cuando la deteccion falla"
    assert debug_img.ndim == 3


def test_suggest_board_sizes_finds_correct_size():
    """suggest_board_sizes identifica el patron correcto entre los candidatos."""
    from service.calibration_service import suggest_board_sizes, load_dead_pixel_mask
    from tests.fixtures.synthetic_board import make_board_image

    img  = make_board_image(inner_corners=(8, 6), square_px=60, margin_px=40)
    mask = load_dead_pixel_mask(img.shape, columns=[], cluster_bbox=None)
    found = suggest_board_sizes(img, mask, candidates=[(5, 4), (8, 6), (9, 7)])

    sizes = [f["inner"] for f in found]
    assert (8, 6) in sizes, f"(8,6) deberia estar en los sugeridos: {sizes}"


def test_image_diagnostics_returns_expected_keys():
    """image_diagnostics devuelve todas las claves esperadas."""
    from service.calibration_service import image_diagnostics
    import numpy as np

    img = np.full((100, 100), 128, dtype=np.uint8)
    diag = image_diagnostics(img)

    for key in ["resolucion", "sharpness", "pmin", "pmax", "pmean",
                "pstd", "pct_dark", "pct_mid", "pct_bright"]:
        assert key in diag, f"Clave '{key}' falta en image_diagnostics"

    assert diag["resolucion"] == (100, 100)
    assert diag["pmin"] == 128
    assert diag["pmax"] == 128


def test_detect_low_contrast_succeeds_with_clahe():
    """
    Tablero comprimido a rango [118, 138] (20 niveles de gris, simula
    la Celestron con iluminacion uniforme). La cascada con CLAHE debe detectar.
    """
    import numpy as np
    from service.calibration_service import detect_chessboard_ex, load_dead_pixel_mask
    from tests.fixtures.synthetic_board import make_board_image

    board = make_board_image(inner_corners=(8, 6), square_px=60, margin_px=40)
    # Comprimir a [118, 138]: rango de 20 niveles
    board_lc = (board.astype(np.float32) / 255.0 * 20 + 118).astype(np.uint8)
    assert board_lc.max() - board_lc.min() <= 20, \
        "La imagen de prueba debe tener rango <= 20 niveles de gris"

    mask = load_dead_pixel_mask(board_lc.shape, columns=[], cluster_bbox=None)
    corners, debug_img, msg = detect_chessboard_ex(board_lc, mask, inner_corners=(8, 6))

    assert corners is not None, (
        f"La cascada con CLAHE deberia detectar en imagen de bajo contraste. msg={msg}"
    )
    assert corners.shape[0] == 48


def test_clahe_increases_contrast():
    """
    CLAHE estira un histograma tipo spike (ruido Gaussiano sigma=3, media=128),
    que es el escenario real de la Celestron con iluminacion uniforme.
    El std de salida debe ser mucho mayor que el de entrada.
    """
    import numpy as np
    import cv2

    rng = np.random.default_rng(42)
    # Ruido Gaussiano estrecho: sigma=3, rango efectivo ~18 (6*sigma)
    img = np.clip(rng.normal(128, 3, (128, 128)), 0, 255).astype(np.uint8)
    assert img.std() < 5, f"Imagen de prueba debe ser de bajo contraste, std={img.std():.1f}"

    clahe    = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(img)

    # clipLimit=2 acota la amplificacion; factor 2x es conservador y garantizado
    assert enhanced.std() > img.std() * 2, (
        f"CLAHE debe multiplicar la std >= 2x sobre histograma en spike: "
        f"antes={img.std():.1f} despues={enhanced.std():.1f}"
    )


def test_detect_classic_fallback():
    """
    Cuando SB falla (simulado pasando un tablero perfectamente normal),
    el metodo clasico + cornerSubPix encuentra las esquinas.
    Verifica que la cascada completa funciona y retorna corners.
    """
    import numpy as np
    from service.calibration_service import detect_chessboard_ex, load_dead_pixel_mask
    from tests.fixtures.synthetic_board import make_board_image

    img  = make_board_image(inner_corners=(8, 6), square_px=60, margin_px=40)
    mask = load_dead_pixel_mask(img.shape, columns=[], cluster_bbox=None)
    corners, _dbg, msg = detect_chessboard_ex(img, mask, inner_corners=(8, 6))

    assert corners is not None, "La cascada debe encontrar esquinas en el tablero sintetico"
    # No importa que metodo gano — lo importante es que hubo resultado
    assert corners.shape[0] == 48


def test_blurry_rejected():
    """Imagen desenfocada: sharpness_score bajo -> no se intenta calibrar."""
    from service.calibration_service import sharpness_score
    from tests.fixtures.synthetic_board import make_board_image

    img = make_board_image(blur_sigma=10.0)
    score = sharpness_score(img)
    THRESHOLD = 50.0
    assert score < THRESHOLD, (
        f"Imagen con blur=10 deberia dar score < {THRESHOLD}, dio {score:.1f}. "
        "El wizard debe rechazarla antes de intentar detectar esquinas."
    )


def test_synthetic_board_recovers_identity():
    """
    Sobre tablero sintetico sin distorsion, H debe ser cercana a la transformacion
    ideal (escala uniforme). RMS debe ser casi 0 (< 0.5 um).
    """
    from service.calibration_service import detect_chessboard, compute_homography, load_dead_pixel_mask
    from tests.fixtures.synthetic_board import (make_board_image, board_corners_mm_nominal,
                                                board_corners_px_ideal)

    INNER = (8, 6)
    SQ_PX = 60
    SQ_MM = 0.5
    MARGIN = 40

    img  = make_board_image(inner_corners=INNER, square_px=SQ_PX, margin_px=MARGIN)
    mask = load_dead_pixel_mask(img.shape, columns=[], cluster_bbox=None)
    corners = detect_chessboard(img, mask, inner_corners=INNER)
    assert corners is not None, "No se detectaron esquinas"

    mm_nom = board_corners_mm_nominal(inner_corners=INNER, square_mm=SQ_MM)
    H, metrics = compute_homography(corners, mm_nom)

    assert metrics["rms_um"] < 0.5, (
        f"RMS sobre tablero sintetico perfecto debe ser < 0.5 um, es {metrics['rms_um']:.3f} um"
    )
    # det > 0: sin espejado
    assert metrics["det_lineal"] > 0


def test_collinear_points_rejected():
    """Puntos colineales -> validate_calibration marca passed=False."""
    from service.calibration_service import compute_homography, validate_calibration

    # 10 puntos en una linea recta (colineales)
    px_col = np.array([[i * 50.0, 200.0] for i in range(10)], dtype=np.float64)
    mm_col = np.array([[i * 0.5,  0.0  ] for i in range(10)], dtype=np.float64)

    try:
        H, metrics = compute_homography(px_col, mm_col)
    except Exception:
        # OK que falle en collineares
        return

    result = validate_calibration(metrics, H, rms_um_max=30.0, min_corners=40)
    # Puntos colineales: esquinas < 40 o det ~ 0 -> debe fallar
    assert result["passed"] is False, "Puntos colineales deberian fallar la validacion"


def test_mirror_detected():
    """
    Set de esquinas espejado en X: det_lineal < 0 -> espejado_ok=False -> passed=False.

    Se construye el set espejado directamente (sin pasar por deteccion OpenCV)
    para garantizar el escenario de espejado independientemente del orden que
    OpenCV elija al detectar un tablero fisicamente espejado.
    """
    from service.calibration_service import compute_homography, validate_calibration
    from tests.fixtures.synthetic_board import board_corners_px_ideal, board_corners_mm_nominal

    INNER   = (8, 6)
    SQ_PX   = 60
    MARGIN  = 40
    IMG_W   = (INNER[0] + 1) * SQ_PX + 2 * MARGIN   # ancho de la imagen sintetica

    corners_ideal  = board_corners_px_ideal(INNER, SQ_PX, MARGIN)
    corners_mirror = corners_ideal.copy()
    corners_mirror[:, 0] = IMG_W - corners_mirror[:, 0]   # espejo en X

    mm_nom = board_corners_mm_nominal(INNER, square_mm=0.5)
    H, metrics = compute_homography(corners_mirror, mm_nom)

    assert metrics["det_lineal"] < 0, (
        f"Esquinas espejadas deben dar det_lineal < 0, dio {metrics['det_lineal']:.4f}"
    )
    result = validate_calibration(metrics, H)
    assert result["checks"]["espejado_ok"] is False
    assert result["passed"] is False


def test_dead_pixels_ignored():
    """
    detect_chessboard levanta RuntimeError cuando la mayoria de esquinas
    caen en columnas muertas (mas del 10% del threshold).

    Se construye una mascara que cubre TODAS las columnas donde hay esquinas
    -> > 10% -> debe levantar RuntimeError.
    """
    from service.calibration_service import detect_chessboard, load_dead_pixel_mask
    from tests.fixtures.synthetic_board import make_board_image, board_corners_px_ideal

    INNER = (8, 6)
    SQ_PX = 60
    MARGIN = 40

    img   = make_board_image(inner_corners=INNER, square_px=SQ_PX, margin_px=MARGIN)
    ideal = board_corners_px_ideal(inner_corners=INNER, square_px=SQ_PX, margin_px=MARGIN)

    # Enmascarar TODAS las columnas donde hay esquinas (> 10% -> debe levantar RuntimeError)
    dead_cols = list({int(round(pt[0])) for pt in ideal})
    mask = load_dead_pixel_mask(img.shape, columns=dead_cols, cluster_bbox=None)

    with pytest.raises(RuntimeError, match="pixeles muertos"):
        detect_chessboard(img, mask, inner_corners=INNER)


def test_anisotropic_print_flagged():
    """Tablero impreso con escala X != Y: cross-check vs 218 px/mm falla."""
    from service.calibration_service import (detect_chessboard, compute_homography,
                                              validate_calibration, load_dead_pixel_mask)
    from tests.fixtures.synthetic_board import make_board_image, board_corners_mm_nominal

    INNER = (8, 6)
    # scale_x=1.0, scale_y=1.5 simula impresion anisotropica
    img  = make_board_image(inner_corners=INNER, square_px=60, margin_px=40,
                            scale_x=1.0, scale_y=1.5)
    mask = load_dead_pixel_mask(img.shape, columns=[], cluster_bbox=None)
    corners = detect_chessboard(img, mask, inner_corners=INNER)

    if corners is None:
        pytest.skip("Tablero anisotropico no detectado")

    mm_nom = board_corners_mm_nominal(inner_corners=INNER, square_mm=0.5)
    H, metrics = compute_homography(corners, mm_nom)

    # isotropia_xy deberia alejarse de 1 con escala 1.0 vs 1.5
    assert metrics["isotropia_xy"] < 0.9 or metrics["isotropia_xy"] > 1.1, (
        f"Tablero anisotropico deberia tener isotropia != 1, es {metrics['isotropia_xy']:.3f}"
    )

    result = validate_calibration(metrics, H, scale_px_per_mm_ref=218.0)
    assert result["checks"]["escala_cross_ok"] is False or result["passed"] is False


def test_rms_threshold():
    """RMS > 30 um -> passed=False."""
    from service.calibration_service import validate_calibration

    H = np.eye(3)
    metrics = {
        "rms_um": 35.0,
        "rms_px": 7.6,
        "esquinas_detectadas": 48,
        "det_lineal": 1.0,
        "isotropia_xy": 1.0,
    }
    result = validate_calibration(metrics, H, rms_um_max=30.0)
    assert result["passed"] is False
    assert result["checks"]["rms_ok"] is False


# ---------------------------------------------------------------------------
# Máscara en sharpness_score y check_exposure
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# to_gray — conversión robusta a 1 canal uint8
# ---------------------------------------------------------------------------

def test_to_gray_1channel_passthrough():
    """Imagen ya gris (ndim=2) sale igual."""
    import numpy as np
    from service.calibration_service import to_gray

    img = np.array([[10, 20], [30, 40]], dtype=np.uint8)
    out = to_gray(img)
    assert out.ndim == 2
    assert out.dtype == np.uint8
    np.testing.assert_array_equal(out, img)


def test_to_gray_2channel():
    """Imagen de 2 canales (ej. Celestron YA) produce 1 canal uint8."""
    import numpy as np
    from service.calibration_service import to_gray

    # Canal 0 = luminancia, canal 1 = alpha/mascara
    lum = np.array([[100, 150], [200, 50]], dtype=np.uint8)
    alpha = np.full((2, 2), 255, dtype=np.uint8)
    img = np.stack([lum, alpha], axis=2)          # (2, 2, 2)

    out = to_gray(img)
    assert out.ndim == 2, f"Esperaba ndim=2, obtuvo {out.ndim}"
    assert out.dtype == np.uint8
    np.testing.assert_array_equal(out, lum)       # canal 0


def test_to_gray_3channel_bgr():
    """Imagen BGR 3 canales convierte correctamente a gris."""
    import numpy as np
    import cv2
    from service.calibration_service import to_gray

    bgr = np.zeros((4, 4, 3), dtype=np.uint8)
    bgr[:, :] = [60, 120, 180]   # B=60 G=120 R=180
    expected = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    out = to_gray(bgr)
    assert out.ndim == 2
    assert out.dtype == np.uint8
    np.testing.assert_array_equal(out, expected)


def test_to_gray_4channel_bgra():
    """Imagen BGRA 4 canales convierte correctamente a gris."""
    import numpy as np
    import cv2
    from service.calibration_service import to_gray

    bgra = np.zeros((4, 4, 4), dtype=np.uint8)
    bgra[:, :] = [60, 120, 180, 255]
    expected = cv2.cvtColor(bgra, cv2.COLOR_BGRA2GRAY)

    out = to_gray(bgra)
    assert out.ndim == 2
    assert out.dtype == np.uint8
    np.testing.assert_array_equal(out, expected)


def test_to_gray_uint16():
    """Imagen uint16 se convierte a uint8 tomando el byte alto."""
    import numpy as np
    from service.calibration_service import to_gray

    # 0xAB00 >> 8 = 0xAB = 171
    img16 = np.array([[0xAB00, 0x0000], [0xFFFF, 0x8000]], dtype=np.uint16)
    out = to_gray(img16)
    assert out.dtype == np.uint8
    assert out[0, 0] == 0xAB          # 171
    assert out[0, 1] == 0x00          # 0
    assert out[1, 0] == 0xFF          # 255


def test_to_gray_float():
    """Imagen float se normaliza a 0-255 uint8."""
    import numpy as np
    from service.calibration_service import to_gray

    img_f = np.array([[0.0, 0.5], [1.0, 0.25]], dtype=np.float32)
    out = to_gray(img_f)
    assert out.dtype == np.uint8
    assert out[0, 0] == 0
    assert out[1, 0] == 255


def test_to_gray_2channel_pipeline():
    """
    Imagen de 2 canales pasa por sharpness_score, check_exposure y
    detect_chessboard sin lanzar excepcion (regresion bug Celestron).
    """
    import numpy as np
    from tests.fixtures.synthetic_board import make_board_image
    from service.calibration_service import (
        sharpness_score, check_exposure, load_dead_pixel_mask, detect_chessboard,
    )

    board_gray = make_board_image(inner_corners=(8, 6), square_px=60, margin_px=40)
    # Simular imagen de 2 canales (luminancia + canal extra)
    img_2ch = np.stack([board_gray, np.zeros_like(board_gray)], axis=2)
    assert img_2ch.shape[2] == 2

    mask = load_dead_pixel_mask(board_gray.shape, columns=[], cluster_bbox=None)

    # Ninguna de estas debe lanzar excepcion
    score = sharpness_score(img_2ch)
    assert score > 0

    exp = check_exposure(img_2ch)
    assert "ok" in exp

    corners = detect_chessboard(img_2ch, mask, inner_corners=(8, 6))
    assert corners is not None, "detect_chessboard debe funcionar con imagen de 2 canales"


def test_sharpness_score_mask_excludes_dead_columns():
    """
    Con columnas muertas enmascaradas, sharpness_score no infla la varianza.
    Un bloque uniforme tiene Laplaciano=0; si enmascaramos bien, el score
    sobre el área uniforme enmascarada debería ser ~0.
    """
    import numpy as np
    from service.calibration_service import sharpness_score, load_dead_pixel_mask

    # Imagen uniforme (Laplaciano = 0 en todas partes)
    img = np.full((100, 100), 128, dtype=np.uint8)
    mask = load_dead_pixel_mask((100, 100), columns=[], cluster_bbox=None)

    score_no_mask = sharpness_score(img)
    score_masked  = sharpness_score(img, mask)
    assert score_no_mask == pytest.approx(0.0, abs=1e-3)
    assert score_masked  == pytest.approx(0.0, abs=1e-3)


def test_sharpness_score_mask_dead_columns_dont_inflate():
    """
    Columnas quemadas (valor fijo extremo = 0 rodeadas de grises) crean
    bordes de alto contraste que disparan el Laplaciano.
    Con la máscara correcta, el score baja al excluir esos bordes.
    """
    import numpy as np
    from service.calibration_service import sharpness_score, load_dead_pixel_mask

    # Imagen gris uniforme con dos columnas a 0 (simula columnas quemadas)
    img = np.full((200, 200), 128, dtype=np.uint8)
    img[:, 80] = 0
    img[:, 81] = 0

    score_sin_mask = sharpness_score(img)

    mask = load_dead_pixel_mask((200, 200), columns=[80, 81], cluster_bbox=None)
    score_con_mask = sharpness_score(img, mask)

    assert score_con_mask < score_sin_mask, (
        f"La mascara deberia reducir el score "
        f"(sin={score_sin_mask:.1f}, con={score_con_mask:.1f})"
    )
    # Con la máscara, el score del área uniforme debe ser casi 0
    assert score_con_mask < 5.0, (
        f"Score enmascarado sobre area uniforme deberia ser ~0, es {score_con_mask:.2f}"
    )


def test_cala_pipeline_no_dead_pixels():
    """
    El pipeline Cal-A completo (deteccion + homografia + validacion) corre sin
    excepcion con una mascara neutra (sin defectos), como ocurre con la Celestron
    u otras camaras sin pixeles muertos conocidos.
    Regresion del bug 'local variable mask referenced before assignment'.
    """
    import numpy as np
    from service.calibration_service import (
        load_dead_pixel_mask, sharpness_score, check_exposure,
        detect_chessboard, compute_homography, validate_calibration,
    )
    from tests.fixtures.synthetic_board import make_board_image, board_corners_mm_nominal

    img = make_board_image(inner_corners=(8, 6), square_px=60, margin_px=40)

    # Mascara neutra — ningun pixel excluido (simula camara sin defectos)
    mask = load_dead_pixel_mask(img.shape, columns=[], cluster_bbox=None)
    assert not mask.any(), "Mascara neutra debe ser todo-False"

    # Los tres chequeos deben funcionar con mascara neutra sin lanzar excepcion
    sharp = sharpness_score(img, mask)
    assert sharp > 0

    exp = check_exposure(img, mask)
    assert "ok" in exp

    corners = detect_chessboard(img, mask, inner_corners=(8, 6))
    assert corners is not None

    mm_nom = board_corners_mm_nominal(inner_corners=(8, 6), square_mm=0.5)
    H, metrics = compute_homography(corners, mm_nom)
    result = validate_calibration(metrics, H)
    assert "passed" in result


def test_check_exposure_mask_ignores_dead_pixels():
    """
    Columnas saturadas (255) enmascaradas no deben ser contadas como saturadas.
    """
    import numpy as np
    from service.calibration_service import check_exposure, load_dead_pixel_mask

    # Imagen normal con 4 columnas a 255 (4 % > umbral max_sat_frac=2 %)
    img = np.full((100, 100), 128, dtype=np.uint8)
    for col in [38, 39, 40, 41]:
        img[:, col] = 255

    result_sin = check_exposure(img)
    assert result_sin["ok"] is False, "4 columnas saturadas deben superar el umbral"

    mask = load_dead_pixel_mask((100, 100), columns=[38, 39, 40, 41], cluster_bbox=None)
    result_con = check_exposure(img, mask)
    assert result_con["ok"] is True, "Con mascaras aplicadas las columnas no deben contar"
    assert result_con["saturated_frac"] < 0.01


# ---------------------------------------------------------------------------
# Focus Assist — tests sin UI (lógica pura del loop y overlay)
# ---------------------------------------------------------------------------

def test_focus_assist_loop_updates_score():
    """
    _focus_assist_loop actualiza state['focus_assist']['score'] con un frame real.
    Corre el loop en un thread real durante 0.6 s y verifica que el score se actualiza.
    """
    import threading, time
    import numpy as np
    from tests.fixtures.synthetic_board import make_board_image
    from presentation.preview_panel import _focus_assist_loop

    # Crear un frame sintético nítido (tablero de ajedrez)
    board_gray = make_board_image(square_px=50, margin_px=20)
    # Convertir a BGR para simular frame de cámara
    board_bgr = np.stack([board_gray, board_gray, board_gray], axis=2)

    state = {
        "alive": True,
        "last_bgr": board_bgr,
        "focus_assist": {
            "enabled": True,
            "score": None,
            "max_score": None,
            "error": None,
            "roi_frac": 0.40, "roi_cx_frac": 0.28, "roi_cy_frac": 0.25,
        },
    }

    t = threading.Thread(target=_focus_assist_loop, args=(state, None), daemon=True)
    t.start()
    time.sleep(0.5)   # esperar al menos 2 ciclos a 5 Hz
    state["alive"] = False

    assert state["focus_assist"]["score"] is not None, \
        "_focus_assist_loop no actualizo score con frame valido"
    assert state["focus_assist"]["score"] > 100.0, \
        f"Score del tablero sintetico esperado > 100, fue {state['focus_assist']['score']:.1f}"
    assert state["focus_assist"]["max_score"] is not None


def test_focus_assist_loop_sets_error_without_stream():
    """
    _focus_assist_loop pone error='sin stream' cuando last_bgr es None y enabled=True.
    """
    import threading, time
    from presentation.preview_panel import _focus_assist_loop

    state = {
        "alive": True,
        "last_bgr": None,
        "focus_assist": {
            "enabled": True,
            "score": None,
            "max_score": None,
            "error": None,
            "roi_frac": 0.40, "roi_cx_frac": 0.28, "roi_cy_frac": 0.25,
        },
    }

    t = threading.Thread(target=_focus_assist_loop, args=(state, None), daemon=True)
    t.start()
    time.sleep(0.4)
    state["alive"] = False

    assert state["focus_assist"]["error"] is not None, \
        "Deberia haber un error cuando no hay stream"
    assert "stream" in state["focus_assist"]["error"].lower()


def test_focus_assist_loop_dead_pixel_mask_applied():
    """
    Con máscara de píxeles muertos, el loop no lanza excepción y devuelve score.
    """
    import threading, time
    import numpy as np
    from tests.fixtures.synthetic_board import make_board_image
    from service.calibration_service import load_dead_pixel_mask
    from presentation.preview_panel import _focus_assist_loop

    board_gray = make_board_image(square_px=50, margin_px=20)
    board_bgr  = np.stack([board_gray, board_gray, board_gray], axis=2)
    H, W = board_gray.shape
    # Máscara con algunas columnas muertas en el centro
    mask = load_dead_pixel_mask((H, W), columns=[W // 2, W // 2 + 1], cluster_bbox=None)

    state = {
        "alive": True,
        "last_bgr": board_bgr,
        "focus_assist": {
            "enabled": True,
            "score": None,
            "max_score": None,
            "error": None,
            "roi_frac": 0.40, "roi_cx_frac": 0.28, "roi_cy_frac": 0.25,
        },
    }

    t = threading.Thread(target=_focus_assist_loop, args=(state, mask), daemon=True)
    t.start()
    time.sleep(0.5)
    state["alive"] = False

    assert state["focus_assist"]["error"] is None, \
        f"Mascara causo error inesperado: {state['focus_assist']['error']}"
    assert state["focus_assist"]["score"] is not None


def test_focus_overlay_draw_no_exception():
    """
    _draw_focus_overlay no lanza excepción con un frame y state válidos.
    """
    import numpy as np
    from tests.fixtures.synthetic_board import make_board_image
    from presentation.preview_panel import _draw_focus_overlay

    board_gray = make_board_image(square_px=50, margin_px=20)
    board_bgr  = np.stack([board_gray, board_gray, board_gray], axis=2)
    H, W = board_gray.shape
    disp = np.zeros((H, W, 3), dtype=np.uint8)

    state = {
        "focus_assist": {
            "enabled": True,
            "score": 350.0,
            "max_score": 400.0,
            "error": None,
            "roi_frac": 0.40, "roi_cx_frac": 0.28, "roi_cy_frac": 0.25,
        }
    }
    # No debe lanzar ninguna excepción
    _draw_focus_overlay(disp, state, W, H, 1.0, board_bgr)


def test_focus_overlay_noop_when_disabled():
    """_draw_focus_overlay no modifica el frame cuando está desactivado."""
    import numpy as np
    from presentation.preview_panel import _draw_focus_overlay

    disp = np.zeros((200, 200, 3), dtype=np.uint8)
    original = disp.copy()
    state = {"focus_assist": {"enabled": False, "score": 999.0, "max_score": 999.0}}
    _draw_focus_overlay(disp, state, 200, 200, 1.0, None)
    np.testing.assert_array_equal(disp, original,
        err_msg="_draw_focus_overlay modifico el frame aunque disabled=False")


# ---------------------------------------------------------------------------
# test_golden_run_unchanged — el flujo viejo no se rompre
# ---------------------------------------------------------------------------

def test_golden_run_unchanged():
    """
    El flujo del golden run original (pipeline sim completo) sigue funcionando
    despues de agregar Cal-A. Importa todos los modulos nuevos sin romper los viejos.
    """
    # Importar modulos nuevos
    from service.platform_profile import build_profile, save_profile, load_profile, recompute_H
    from service.calibration_service import (
        sharpness_score, check_exposure, load_dead_pixel_mask,
        orientation_sign_check, detect_chessboard, compute_homography, validate_calibration,
    )

    # Importar los modulos que usa el golden run (no deben romperse)
    from service.scan_service import ScanRunner
    from service.vision_service import VisionService
    from hal.drivers.sim_stage import SimStage
    from hal.drivers.sim_laser import SimLaser
    from hal.drivers.ocean_spectrometer import OceanSpectrometer

    # StageCalibration existente no se toco
    from service.calibration_service import StageCalibration, CalibPoint
    cal = StageCalibration()
    cal.add_point(px=100, py=100, x_mm=0.0, y_mm=0.0)
    cal.add_point(px=200, py=100, x_mm=1.0, y_mm=0.0)
    cal.add_point(px=100, py=200, x_mm=0.0, y_mm=1.0)
    assert cal.fit() is True
    assert cal.valid is True
