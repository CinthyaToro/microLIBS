# -*- coding: utf-8 -*-
"""
test_keepbest_logic.py — Test unitario de la lógica keep-best para selección de frames.

Valida la lógica de _SpecModule.acquire() sin hardware:
- Frame selection por pico máximo en canal A
- Descarte de frames saturados (cualquier canal >= 16000)
- Manejo de casos borde (todos saturados, todos baseline)
"""

import pytest


def select_best_frame(frames_data, channel_names=None):
    """
    Simula la lógica de keep-best: selecciona el frame de mayor pico en canal A
    entre los frames VÁLIDOS (sin saturación en ningún canal).

    Args:
        frames_data: list of {
            'intensities_A': [...],
            'intensities_B': [...],
            'intensities_C': [...],
            'index': int
        }
        channel_names: ['A', 'B', 'C'] para logging

    Returns: {
        'best_index': int,
        'best_intensities_A': [...],
        'best_peak_value': float,
        'n_frames_read': int,
        'saturated': bool,
        'reason': str
    }
    """
    ADC_SATURATION = 16000

    valid_frames = []
    saturated_frames = []

    for frame in frames_data:
        max_A = max(frame['intensities_A']) if frame['intensities_A'] else 0
        max_B = max(frame['intensities_B']) if frame['intensities_B'] else 0
        max_C = max(frame['intensities_C']) if frame['intensities_C'] else 0

        is_saturated = (max_A >= ADC_SATURATION or
                       max_B >= ADC_SATURATION or
                       max_C >= ADC_SATURATION)

        if is_saturated:
            saturated_frames.append({
                'index': frame['index'],
                'peak_A': max_A,
                'max_all': max(max_A, max_B, max_C)
            })
        else:
            valid_frames.append({
                'index': frame['index'],
                'intensities_A': frame['intensities_A'],
                'peak_A': max_A
            })

    if not valid_frames and not saturated_frames:
        # Sin frames
        return {
            'best_index': None,
            'best_intensities_A': None,
            'best_peak_value': 0,
            'n_frames_read': len(frames_data),
            'saturated': False,
            'reason': 'no frames available'
        }

    if valid_frames:
        # Hay frames válidos: elegir el de mayor pico
        best = max(valid_frames, key=lambda f: f['peak_A'])
        return {
            'best_index': best['index'],
            'best_intensities_A': best['intensities_A'],
            'best_peak_value': best['peak_A'],
            'n_frames_read': len(frames_data),
            'saturated': False,
            'reason': 'selected best valid frame'
        }
    else:
        # Todos saturados: elegir el menos saturado
        best = min(saturated_frames, key=lambda f: f['max_all'])
        return {
            'best_index': best['index'],
            'best_intensities_A': None,  # No retornamos datos de un frame saturado
            'best_peak_value': best['peak_A'],
            'n_frames_read': len(frames_data),
            'saturated': True,
            'reason': 'all frames saturated, selected least saturated'
        }


class TestKeepBestLogic:
    """Test cases para la selección keep-best de frames."""

    def test_select_frame_with_peak_among_baselines(self):
        """3 frames: dos baseline + uno con pico → elegir el del pico."""
        frames = [
            {
                'index': 0,
                'intensities_A': [800, 805, 810, 808],
                'intensities_B': [1000, 1005, 1010],
                'intensities_C': [600, 605, 610]
            },
            {
                'index': 1,
                'intensities_A': [800, 2000, 800, 800],  # Pico en 2000
                'intensities_B': [1000, 1050, 1000],
                'intensities_C': [600, 650, 600]
            },
            {
                'index': 2,
                'intensities_A': [800, 810, 805, 808],
                'intensities_B': [1000, 1010, 1005],
                'intensities_C': [600, 610, 605]
            }
        ]

        result = select_best_frame(frames)

        assert result['best_index'] == 1, "Debe elegir frame 1 (con pico)"
        assert result['best_peak_value'] == 2000, "Pico máximo debe ser 2000"
        assert result['saturated'] == False
        assert result['n_frames_read'] == 3

    def test_discard_saturated_frame(self):
        """Un frame saturado debe descartarse aunque tenga el pico más alto."""
        frames = [
            {
                'index': 0,
                'intensities_A': [800, 900, 850],
                'intensities_B': [1000, 1100, 1050],
                'intensities_C': [600, 700, 650]
            },
            {
                'index': 1,
                'intensities_A': [16200, 16300, 16250],  # SATURADO
                'intensities_B': [1000, 1050, 1000],
                'intensities_C': [600, 650, 600]
            },
            {
                'index': 2,
                'intensities_A': [800, 950, 850],
                'intensities_B': [1000, 1150, 1050],
                'intensities_C': [600, 750, 650]
            }
        ]

        result = select_best_frame(frames)

        assert result['best_index'] == 2, "Debe elegir frame 2 (válido, no el saturado)"
        assert result['best_peak_value'] == 950, "Pico debe ser 950, no 16300"
        assert result['saturated'] == False

    def test_all_frames_saturated(self):
        """Todos los frames saturan → devolver el menos saturado + flag."""
        frames = [
            {
                'index': 0,
                'intensities_A': [16100, 16200],  # SATURADO
                'intensities_B': [16000, 16100],
                'intensities_C': [600, 700]
            },
            {
                'index': 1,
                'intensities_A': [15500, 16000],  # SATURADO (B>=16000), pero menos que frame 0
                'intensities_B': [16000, 16050],
                'intensities_C': [600, 650]
            }
        ]

        result = select_best_frame(frames)

        assert result['saturated'] == True, "Flag saturated debe ser True"
        assert result['best_index'] == 1, "Debe elegir frame 1 (menos saturado)"
        assert 'saturated' in result['reason'].lower(), "Log debe mencionar saturación"

    def test_all_baseline_no_peak(self):
        """Todos los frames son baseline (sin pico) → elegir el de mayor pico igual."""
        frames = [
            {
                'index': 0,
                'intensities_A': [800, 815, 810],
                'intensities_B': [1000, 1010, 1005],
                'intensities_C': [600, 610, 605]
            },
            {
                'index': 1,
                'intensities_A': [800, 850, 810],  # Pico más alto (pero aún baseline)
                'intensities_B': [1000, 1020, 1005],
                'intensities_C': [600, 620, 605]
            }
        ]

        result = select_best_frame(frames)

        assert result['best_index'] == 1, "Debe elegir frame 1 (pico más alto, aunque baseline)"
        assert result['best_peak_value'] == 850
        assert result['saturated'] == False

    def test_n_frames_read_logged(self):
        """Verifica que n_frames_read esté en el resultado."""
        frames = [
            {
                'index': 0,
                'intensities_A': [800, 810],
                'intensities_B': [1000, 1010],
                'intensities_C': [600, 610]
            },
            {
                'index': 1,
                'intensities_A': [800, 900],
                'intensities_B': [1000, 1100],
                'intensities_C': [600, 700]
            }
        ]

        result = select_best_frame(frames)

        assert result['n_frames_read'] == 2, "Debe reportar 2 frames leídos"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
