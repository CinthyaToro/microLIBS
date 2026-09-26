# -*- coding: utf-8 -*-
"""
tests/fixtures/synthetic_board.py
===================================
Generador de imagenes sinteticas de tablero de ajedrez para tests de Cal-A.

Uso:
    from tests.fixtures.synthetic_board import make_board_image, board_corners_px
"""

import numpy as np


def make_board_image(
    inner_corners: tuple = (8, 6),
    square_px: int = 60,
    margin_px: int = 40,
    blur_sigma: float = 0.0,
    mirror_x: bool = False,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> np.ndarray:
    """
    Genera una imagen uint8 de un tablero de ajedrez sintetico.

    Parametros
    ----------
    inner_corners : (cols, rows) de esquinas interiores  (default 8x6 = 48 esquinas)
    square_px     : tamano de cada casilla en pixeles
    margin_px     : margen alrededor del tablero
    blur_sigma    : sigma del desenfoque gaussiano (0 = sin desenfoque)
    mirror_x      : si True, espeja la imagen horizontalmente
    scale_x/y     : factores de escala anisotropica (1.0 = isotropico)
    """
    cols_i, rows_i = inner_corners
    n_cols = cols_i + 1   # casillas en X
    n_rows = rows_i + 1   # casillas en Y

    sq_x = int(square_px * scale_x)
    sq_y = int(square_px * scale_y)

    w = n_cols * sq_x + 2 * margin_px
    h = n_rows * sq_y + 2 * margin_px

    img = np.ones((h, w), dtype=np.uint8) * 255

    for r in range(n_rows):
        for c in range(n_cols):
            if (r + c) % 2 == 0:
                x0 = margin_px + c * sq_x
                y0 = margin_px + r * sq_y
                img[y0:y0 + sq_y, x0:x0 + sq_x] = 0

    if blur_sigma > 0:
        try:
            import cv2
            ksize = int(blur_sigma * 6) | 1   # impar
            img = cv2.GaussianBlur(img, (ksize, ksize), blur_sigma)
        except ImportError:
            from scipy.ndimage import gaussian_filter
            img = (gaussian_filter(img.astype(float), blur_sigma)).astype(np.uint8)

    if mirror_x:
        img = img[:, ::-1]

    return img


def board_corners_mm_nominal(
    inner_corners: tuple = (8, 6),
    square_mm: float = 0.5,
) -> np.ndarray:
    """
    Devuelve las coordenadas nominales (en mm) de las esquinas interiores
    del tablero en orden row-major (igual que OpenCV findChessboardCorners).

    Shape: (cols_i * rows_i, 2)
    """
    cols_i, rows_i = inner_corners
    pts = []
    for r in range(rows_i):
        for c in range(cols_i):
            pts.append([c * square_mm, r * square_mm])
    return np.array(pts, dtype=np.float64)


def board_corners_px_ideal(
    inner_corners: tuple = (8, 6),
    square_px: int = 60,
    margin_px: int = 40,
) -> np.ndarray:
    """
    Devuelve las coordenadas exactas (en px) de las esquinas interiores
    del tablero sintetico generado por make_board_image (sin escala, sin blur).

    Shape: (cols_i * rows_i, 2)
    """
    cols_i, rows_i = inner_corners
    pts = []
    for r in range(rows_i):
        for c in range(cols_i):
            x = margin_px + (c + 1) * square_px
            y = margin_px + (r + 1) * square_px
            pts.append([float(x), float(y)])
    return np.array(pts, dtype=np.float64)
