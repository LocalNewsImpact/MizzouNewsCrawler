from types import SimpleNamespace

from scripts.scan_production_with_new_detector import map_detection_to_service


def _det(evidence):
    return SimpleNamespace(evidence=evidence)


def test_kansas_reflector_alone_is_not_states_newsroom():
    # Detector claims States Newsroom but only Kansas Reflector appears in evidence
    det = _det(
        {
            "detected_services": ["States Newsroom"],
            "content": ["This story appeared in the Kansas Reflector"],
        }
    )
    assert map_detection_to_service(det) == "Unknown"


def test_states_newsroom_explicit_is_kept():
    # If the evidence explicitly mentions 'States Newsroom', keep it
    det = _det(
        {
            "detected_services": ["States Newsroom"],
            "content": [
                (
                    "This story first appeared in the Kansas Reflector, "
                    "a States Newsroom affiliate."
                )
            ],
        }
    )
    assert map_detection_to_service(det) == "States Newsroom"


def test_wave_is_not_mapped_as_syndicated():
    det = _det(
        {
            "detected_services": ["WAVE"],
            "content": ["Copyright 2024 WAVE. All rights reserved."],
        }
    )
    assert map_detection_to_service(det) == "Unknown"
