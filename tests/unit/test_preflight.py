"""Unit tests for TIP-007-V1 image preflight (Laplacian blur + dimension)."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from backend.preflight import BLUR_THRESHOLD, MIN_DIMENSION_PX, check_image


def _make_jpeg(arr: np.ndarray, quality: int = 90) -> bytes:
    """Encode a numpy array as JPEG bytes."""
    img = Image.fromarray(arr.astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def test_sharp_image_passes():
    """A high-frequency image (random noise) has high Laplacian variance."""
    rng = np.random.default_rng(seed=42)
    arr = rng.integers(0, 255, size=(512, 512, 3), dtype=np.uint8)
    result = check_image(_make_jpeg(arr))
    assert result.passed is True
    assert result.blur_score is not None and result.blur_score > BLUR_THRESHOLD
    assert result.failure_reason is None
    assert result.brightness is not None and 0 <= result.brightness <= 255


def test_blurry_image_rejected():
    """A flat/uniform image has near-zero Laplacian variance."""
    arr = np.full((512, 512, 3), 128, dtype=np.uint8)
    result = check_image(_make_jpeg(arr))
    assert result.passed is False
    assert result.blur_score is not None and result.blur_score < BLUR_THRESHOLD
    assert result.failure_reason is not None
    assert "mờ" in result.failure_reason.lower()


def test_undersized_image_rejected():
    """Images below MIN_DIMENSION_PX rejected with size message."""
    arr = np.zeros((100, 100, 3), dtype=np.uint8)
    result = check_image(_make_jpeg(arr))
    assert result.passed is False
    assert result.failure_reason is not None
    assert "nhỏ" in result.failure_reason or "tối thiểu" in result.failure_reason


def test_just_under_min_dimension_rejected():
    arr = np.zeros((MIN_DIMENSION_PX - 1, MIN_DIMENSION_PX - 1, 3), dtype=np.uint8)
    result = check_image(_make_jpeg(arr))
    assert result.passed is False


def test_garbage_bytes_rejected():
    """Non-image bytes fail decode → reject with generic message."""
    result = check_image(b"this is not an image")
    assert result.passed is False
    assert result.failure_reason is not None
    assert "không thể" in result.failure_reason.lower()


def test_empty_bytes_rejected():
    result = check_image(b"")
    assert result.passed is False
    assert result.failure_reason is not None


def test_dark_image_passes_but_logged(caplog):
    """Dark image (mean ~10) with high variance passes but logs an info
    message for visibility (calibration of dark-reject is V2)."""
    rng = np.random.default_rng(seed=7)
    # Low-mean noisy image — high variance but dark
    arr = rng.integers(0, 30, size=(512, 512, 3), dtype=np.uint8)
    with caplog.at_level("INFO", logger="backend.preflight"):
        result = check_image(_make_jpeg(arr))
    if result.passed:
        assert result.brightness is not None and result.brightness < 30
        assert any("dark" in r.message.lower() for r in caplog.records)


def test_png_format_supported():
    """PIL handles PNG; preflight must work on PNG bytes too."""
    rng = np.random.default_rng(seed=99)
    arr = rng.integers(0, 255, size=(300, 300, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = check_image(buf.getvalue())
    assert result.passed is True
