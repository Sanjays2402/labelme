from __future__ import annotations

from typing import Final

# (model_id, display_name) pairs for AI-assisted annotation. Shared by
# AiAssistedAnnotationWidget (the dock dropdown) and the Settings dialog's "AI"
# tab so both list the same models from a single source of truth.
AVAILABLE_AI_MODELS: Final[tuple[tuple[str, str], ...]] = (
    ("efficientsam:10m", "EfficientSam (speed)"),
    ("efficientsam:latest", "EfficientSam (accuracy)"),
    ("sam:100m", "Sam (speed)"),
    ("sam:300m", "Sam (balanced)"),
    ("sam:latest", "Sam (accuracy)"),
    ("sam2:small", "Sam2 (speed)"),
    ("sam2:latest", "Sam2 (balanced)"),
    ("sam2:large", "Sam2 (accuracy)"),
    ("sam3:latest", "Sam3"),
)
