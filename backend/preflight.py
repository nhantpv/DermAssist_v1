"""Image preflight — rule-based, CPU-only, OpenCV.

Blueprint REQ-SAF-002 + REQ-FUNC-004. Decisions:
- Laplacian variance threshold = 100 (per Blueprint wireframe §9.2)
- Brightness mean computed but only used to flag extreme cases
  (< 30 = too dark, > 225 = overexposed). Not currently a reject
  reason; logged for visibility, calibration is V2.
- All checks fail-closed: any decode/computation error → reject
  with a generic "Không thể xử lý ảnh" message. Better to bounce a
  weird image than send it to the VLM and get a confusing diagnosis.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Final

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

BLUR_THRESHOLD: Final[float] = 100.0   # Laplacian variance below = blurry
DARK_THRESHOLD: Final[float] = 30.0    # mean intensity below = too dark
BRIGHT_THRESHOLD: Final[float] = 225.0  # mean intensity above = overexposed
MIN_DIMENSION_PX: Final[int] = 256     # per Blueprint §9.2 wireframe


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    blur_score: float | None       # Laplacian variance, None if decode failed
    brightness: float | None       # Mean grayscale intensity 0..255
    failure_reason: str | None     # Vietnamese, user-facing; None if passed


def check_image(image_bytes: bytes) -> PreflightResult:
    """Run blur + dimension + brightness checks. Returns PreflightResult.

    Order of checks (fail-fast):
    1. Decode → if fails, reject with generic message
    2. Dimension check → reject if too small
    3. Blur (Laplacian variance) → reject if below threshold
    4. Brightness — log extremes but pass (calibration deferred)
    """
    # 1. Decode via PIL → numpy. PIL handles more formats than cv2.imread.
    try:
        pil_image = Image.open(io.BytesIO(image_bytes))
        pil_image = pil_image.convert("RGB")
        arr = np.array(pil_image)
    except Exception as e:
        logger.warning("Image decode failed: %s", e)
        return PreflightResult(
            passed=False,
            blur_score=None,
            brightness=None,
            failure_reason="Không thể đọc ảnh. Vui lòng thử ảnh khác.",
        )

    height, width = arr.shape[:2]

    # 2. Dimension check
    if min(width, height) < MIN_DIMENSION_PX:
        return PreflightResult(
            passed=False,
            blur_score=None,
            brightness=None,
            failure_reason=(
                f"Ảnh quá nhỏ ({width}×{height} px). "
                f"Tối thiểu {MIN_DIMENSION_PX}×{MIN_DIMENSION_PX} px."
            ),
        )

    # Convert to grayscale for blur + brightness
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # 3. Blur — Laplacian variance
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # 4. Brightness — mean intensity
    brightness = float(gray.mean())

    # Reject on blur
    if blur_score < BLUR_THRESHOLD:
        return PreflightResult(
            passed=False,
            blur_score=blur_score,
            brightness=brightness,
            failure_reason=(
                f"Ảnh quá mờ (variance: {blur_score:.0f}, "
                f"ngưỡng tối thiểu: {int(BLUR_THRESHOLD)}). "
                f"Vui lòng chụp lại với ánh sáng tốt và máy ảnh ổn định."
            ),
        )

    # Brightness extremes — log only, do not reject (calibration V2)
    if brightness < DARK_THRESHOLD:
        logger.info("Image is dark (brightness=%.1f) but passing", brightness)
    elif brightness > BRIGHT_THRESHOLD:
        logger.info("Image is overexposed (brightness=%.1f) but passing", brightness)

    return PreflightResult(
        passed=True,
        blur_score=blur_score,
        brightness=brightness,
        failure_reason=None,
    )
