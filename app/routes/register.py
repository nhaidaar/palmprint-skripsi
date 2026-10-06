import binascii
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import (
    DEV_FEATURES_ENABLED,
    DUPLICATE_THRESHOLD,
    REGISTRATION_CAPTURES_PER_HAND,
    REGISTRATION_HANDS,
    REGISTRATION_MIN_VALID_PER_HAND,
)
from app.routes.recognize import decode_base64_image
from app.services.embedding_templates import build_hand_templates, build_overall_template

router = APIRouter()


class RegisterRequest(BaseModel):
    nim: str = ""
    name: str
    images: list
    hands: list[str] = []
    source: str = "camera"
    is_roi: bool = False          # True when the browser pre-cropped all palm ROIs
    rotation_angle: float = 0.0   # Kept for backward compatibility; new ROIs are already aligned


class RegisterResponse(BaseModel):
    success: bool
    user_id: int
    name: str


@router.post("/api/register", response_model=RegisterResponse)
async def register(req: RegisterRequest):
    from app.main import palm_processor, db

    nim = req.nim.strip()
    if not nim:
        raise HTTPException(status_code=400, detail="NIM is required")
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    source = req.source.strip().lower()
    if source not in {"camera", "upload"}:
        raise HTTPException(status_code=400, detail="Invalid registration source")
    if source == "upload" and not DEV_FEATURES_ENABLED:
        raise HTTPException(status_code=403, detail="Upload registration is only available in development mode")

    required_detail = f"Need exactly {REGISTRATION_CAPTURES_PER_HAND} images for each selected hand"
    hands = [hand.lower() for hand in req.hands]
    if not hands:
        raise HTTPException(status_code=400, detail="Select at least one hand to register")
    if len(hands) != len(req.images):
        raise HTTPException(status_code=400, detail=required_detail)
    if any(hand not in REGISTRATION_HANDS for hand in hands):
        raise HTTPException(status_code=400, detail=required_detail)
    selected_hands = tuple(hand for hand in REGISTRATION_HANDS if hand in hands)
    if any(hands.count(hand) != REGISTRATION_CAPTURES_PER_HAND for hand in selected_hands):
        raise HTTPException(status_code=400, detail=required_detail)

    session_id = str(uuid.uuid4())
    # Save to the persistent /data volume if it exists (Docker), otherwise local data/
    base_data_dir = "/data" if os.path.exists("/data") else "data"
    save_dir = os.path.join(base_data_dir, "captures", f"{nim}_{session_id}")
    os.makedirs(save_dir, exist_ok=True)
    import cv2

    samples = []
    for i, img_b64 in enumerate(req.images):
        try:
            frame = decode_base64_image(img_b64)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid image at index {i}") from exc

        cv2.imwrite(os.path.join(save_dir, f"{hands[i]}_{i}.jpg"), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

        if req.is_roi:
            emb, _ = palm_processor.extract_embedding_from_roi(frame)
        else:
            emb, _ = palm_processor.extract_embedding_from_frame(frame)

        if emb is None:
            raise HTTPException(
                status_code=422,
                detail=f"No hand detected in image {i + 1}",
            )
        samples.append({"hand": hands[i], "embedding": emb})

    try:
        templates = build_hand_templates(
            samples,
            required_hands=selected_hands,
            min_per_hand=REGISTRATION_MIN_VALID_PER_HAND,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    template_hands = list(templates.keys())
    template_embeddings = [templates[hand] for hand in template_hands]
    individual_embeddings = []
    individual_embedding_hands = []
    for hand in selected_hands:
        for sample in samples:
            if sample["hand"] == hand:
                individual_embeddings.append(sample["embedding"])
                individual_embedding_hands.append(hand)
    avg_embedding = build_overall_template(templates)

    stored_embeddings = db.get_all_embeddings()
    for hand_template in template_embeddings:
        duplicate_result = palm_processor.compute_similarity(
            hand_template,
            stored_embeddings,
            DUPLICATE_THRESHOLD,
        )
        if duplicate_result["status"] == "ALLOWED":
            raise HTTPException(
                status_code=409,
                detail=f"This palm is already registered as '{duplicate_result['name']}' "
                       f"(similarity {duplicate_result['similarity'] * 100:.0f}%). "
                       "Use a different palm or remove the existing user first.",
            )

    try:
        user_id = db.add_user(
            req.name.strip(),
            avg_embedding,
            nim=nim,
            individual_embeddings=individual_embeddings,
            embedding_hands=individual_embedding_hands,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RegisterResponse(success=True, user_id=user_id, name=req.name.strip())
