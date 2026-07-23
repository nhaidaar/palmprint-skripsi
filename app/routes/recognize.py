import asyncio
import base64
import logging
import re
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import DEV_FEATURES_ENABLED, SIMILARITY_THRESHOLD
from app.services.recognition_service import match_embedding_and_log

log = logging.getLogger("palmgate")
router = APIRouter()
RECOGNITION_DEBUG_DIR = Path("data") / "debug" / "recognize"


class RecognizeRequest(BaseModel):
    image: str
    is_roi: bool = False          # True when the browser has pre-cropped the palm ROI
    rotation_angle: float = 0.0   # Retained for wire compatibility; ignored for aligned client ROIs
    debug_roi: bool = False
    source: str = "scan"


class RecognizeResponse(BaseModel):
    status: str
    name: str
    similarity: float
    closest_match: "str | None" = None
    roi_image: "str | None" = None
    debug_image_paths: "dict[str, str] | None" = None


def decode_base64_image(b64_string: str) -> np.ndarray:
    if "," in b64_string:
        b64_string = b64_string.split(",", 1)[1]
    img_bytes = base64.b64decode(b64_string)
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def encode_roi_image(processed_roi: np.ndarray) -> str | None:
    try:
        roi_uint8 = np.clip(processed_roi, 0, 255).astype(np.uint8)
        ok, data = cv2.imencode(".jpg", cv2.cvtColor(roi_uint8, cv2.COLOR_RGB2BGR))
        if not ok:
            log.warning("RECOGNIZE | ROI preview encoding failed: cv2.imencode returned false")
            return None
        return "data:image/jpeg;base64," + base64.b64encode(data.tobytes()).decode("ascii")
    except Exception as exc:
        log.warning("RECOGNIZE | ROI preview encoding failed: %s", exc)
        return None


def _safe_debug_source(source: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", source.strip().lower()).strip("-") or "scan"


def _write_debug_images(frame: np.ndarray, processed_roi: np.ndarray | None, source: str) -> dict[str, str]:
    RECOGNITION_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}_{_safe_debug_source(source)}"
    paths = {"frame": str(RECOGNITION_DEBUG_DIR / f"{prefix}_frame.jpg")}
    cv2.imwrite(paths["frame"], cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    if processed_roi is not None:
        paths["roi"] = str(RECOGNITION_DEBUG_DIR / f"{prefix}_roi.jpg")
        roi_uint8 = np.clip(processed_roi, 0, 255).astype(np.uint8)
        cv2.imwrite(paths["roi"], cv2.cvtColor(roi_uint8, cv2.COLOR_RGB2BGR))
    return paths


async def save_debug_images(frame: np.ndarray, processed_roi: np.ndarray | None, source: str) -> dict[str, str]:
    return await asyncio.to_thread(_write_debug_images, frame, processed_roi, source)


@router.post("/api/recognize", response_model=RecognizeResponse, response_model_exclude_unset=True)
async def recognize(req: RecognizeRequest):
    from app.main import palm_processor, db

    started_at = time.perf_counter()
    try:
        frame = decode_base64_image(req.image)
        log.debug("RECOGNIZE | decoded image  shape=%s  dtype=%s  payload_len=%d",
                  frame.shape, frame.dtype, len(req.image))
    except Exception as e:
        log.error("RECOGNIZE | image decode failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid image data")

    processed_roi = None
    should_return_roi = DEV_FEATURES_ENABLED and req.debug_roi

    if req.is_roi:
        log.debug("RECOGNIZE | using pre-cropped client ROI — skipping server detection")
        embedding, processed_roi = palm_processor.extract_embedding_from_roi(frame)
    else:
        embedding, processed_roi = palm_processor.extract_embedding_from_frame(frame)
    if not should_return_roi:
        processed_roi = None

    if embedding is None:
        log.warning("RECOGNIZE | returning 422 — no hand detected in frame")
        raise HTTPException(status_code=422, detail="No hand detected")

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    result = match_embedding_and_log(palm_processor, db, embedding, SIMILARITY_THRESHOLD, duration_ms=duration_ms)
    payload = dict(result)
    if should_return_roi:
        payload["debug_image_paths"] = await save_debug_images(frame, processed_roi, req.source)
    if should_return_roi and processed_roi is not None:
        roi_image = encode_roi_image(processed_roi)
        if roi_image:
            payload["roi_image"] = roi_image
    return RecognizeResponse(**payload)
