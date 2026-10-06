from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.config import DUPLICATE_THRESHOLD, REGISTRATION_MIN_VALID_PER_HAND
from app.services.embedding_templates import (
    build_hand_templates,
    build_overall_template,
    l2_normalize,
)

SEED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class SeedEmbeddingResult:
    embedding: np.ndarray
    individual_embeddings: list[np.ndarray]
    variant_count: int
    selected_count: int


@dataclass(frozen=True)
class SeedUsersSummary:
    created: list[str]
    skipped: list[str]
    failed: dict[str, str]


def parse_seed_identity(label: str, demo_nim: str | None = None) -> tuple[str, str]:
    nim, separator, name = label.partition("_")
    if separator and nim.strip() and name.strip():
        return nim.strip(), name.replace("_", " ").strip()
    if demo_nim:
        return demo_nim, label.replace("_", " ").strip()
    raise RuntimeError("Seed labels must use nim_name format, for example 12345_Naufal")


def _demo_nim(index: int) -> str:
    return f"SEED-{index + 1:03d}"


def parse_system_register_folder(label: str) -> tuple[str, str]:
    name, separator, suffix = label.rpartition("_")
    if not separator or suffix.upper() not in {"L", "R"} or not name.strip():
        raise RuntimeError("System register folders must end with _L or _R")
    hand = "left" if suffix.upper() == "L" else "right"
    return name.strip(), hand


def build_seed_embedding(frame_rgb: np.ndarray, palm_processor) -> SeedEmbeddingResult:
    embedding, _ = palm_processor.extract_embedding_from_frame(frame_rgb)
    if embedding is None:
        raise RuntimeError("MediaPipe hand detection failed")
    embedding = embedding.astype(np.float32)
    return SeedEmbeddingResult(
        embedding=embedding,
        individual_embeddings=[embedding],
        variant_count=1,
        selected_count=1,
    )


def build_seed_embedding_from_frames(
    frames_rgb: list[np.ndarray],
    palm_processor,
) -> SeedEmbeddingResult:
    embeddings = []
    for frame_rgb in frames_rgb:
        embedding, _ = palm_processor.extract_embedding_from_frame(frame_rgb)
        if embedding is not None:
            embeddings.append(embedding.astype(np.float32))
    if not embeddings:
        raise RuntimeError("MediaPipe hand detection failed on all frames")
    average = l2_normalize(np.mean(embeddings, axis=0))
    return SeedEmbeddingResult(
        embedding=average,
        individual_embeddings=[item.astype(np.float32) for item in embeddings],
        variant_count=len(frames_rgb),
        selected_count=len(embeddings),
    )


def build_system_register_template(
    frames_rgb: list[np.ndarray],
    palm_processor,
    hand: str,
) -> SeedEmbeddingResult:
    samples = []
    for frame_rgb in frames_rgb:
        embedding, _ = palm_processor.extract_embedding_from_frame(frame_rgb)
        if embedding is not None:
            samples.append({"hand": hand, "embedding": embedding.astype(np.float32)})

    templates = build_hand_templates(
        samples,
        required_hands=(hand,),
        min_per_hand=REGISTRATION_MIN_VALID_PER_HAND,
    )
    embedding = build_overall_template(templates)
    return SeedEmbeddingResult(
        embedding=embedding,
        individual_embeddings=[sample["embedding"].astype(np.float32) for sample in samples],
        variant_count=len(frames_rgb),
        selected_count=len(samples),
    )


def read_image_rgb(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Image could not be read")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def _seed_image_paths(seed_dir: Path) -> list[Path]:
    return sorted(
        path for path in seed_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SEED_IMAGE_EXTENSIONS
    )


def _seed_person_dirs(seed_dir: Path) -> list[Path]:
    return sorted(
        path for path in seed_dir.iterdir()
        if path.is_dir() and _seed_image_paths(path)
    )


def _system_register_person_dirs(seed_dir: Path) -> list[tuple[int, Path, str, str]]:
    parsed = []
    errors = []
    for path in sorted(seed_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir():
            continue
        try:
            name, hand = parse_system_register_folder(path.name)
        except RuntimeError as exc:
            errors.append((path, str(exc)))
            continue
        parsed.append((path, name, hand))

    name_numbers = {
        name: index + 1
        for index, name in enumerate(sorted({name for _, name, _ in parsed}, key=str.lower))
    }
    rows = [(name_numbers[name], path, name, hand) for path, name, hand in parsed]
    rows.extend((0, path, "", error) for path, error in errors)
    return rows


def _existing_user_names(db) -> set[str]:
    return {user["name"] for user in db.get_all_users()}


def _replace_users(db):
    for user in db.get_all_users():
        db.delete_user(user["id"])


def _reject_duplicate_templates(db, palm_processor, templates: list[np.ndarray]):
    stored_embeddings = db.get_all_embeddings()
    for embedding in templates:
        duplicate = palm_processor.compute_similarity(
            embedding,
            stored_embeddings,
            DUPLICATE_THRESHOLD,
        )
        if duplicate["status"] == "ALLOWED":
            raise RuntimeError(f"This palm is already registered as '{duplicate['name']}'")


def seed_system_register_users_from_directory(
    seed_dir: str | Path,
    db,
    palm_processor,
    *,
    replace_users: bool = False,
    read_image=read_image_rgb,
) -> SeedUsersSummary:
    seed_dir = Path(seed_dir)
    if not seed_dir.exists():
        raise RuntimeError(f"Seed directory does not exist: {seed_dir}")

    if replace_users:
        _replace_users(db)

    existing_nims = {user["nim"] for user in db.get_all_users()}
    created = []
    skipped = []
    failed = {}

    for number, person_dir, name, hand_or_error in _system_register_person_dirs(seed_dir):
        try:
            if number == 0:
                raise RuntimeError(hand_or_error)
            hand = hand_or_error
            suffix = "L" if hand == "left" else "R"
            nim = f"{number}-{suffix}"
            label = f"{name} ({hand})"
            if nim in existing_nims:
                skipped.append(label)
                continue

            frames = [read_image(path) for path in _seed_image_paths(person_dir)]
            result = build_system_register_template(frames, palm_processor, hand)
            _reject_duplicate_templates(db, palm_processor, [result.embedding])
            db.add_user(
                name,
                result.embedding,
                nim=nim,
                individual_embeddings=result.individual_embeddings,
                embedding_hands=[hand] * len(result.individual_embeddings),
            )
            created.append(label)
            existing_nims.add(nim)
        except Exception as exc:
            failed[person_dir.name] = str(exc)

    return SeedUsersSummary(created=created, skipped=skipped, failed=failed)


def seed_users_from_directory(
    seed_dir: str | Path,
    db,
    palm_processor,
    *,
    replace_users: bool = False,
    auto_demo_nim: bool = False,
    read_image=read_image_rgb,
) -> SeedUsersSummary:
    seed_dir = Path(seed_dir)
    if not seed_dir.exists():
        raise RuntimeError(f"Seed directory does not exist: {seed_dir}")

    if replace_users:
        _replace_users(db)

    existing_names = _existing_user_names(db)
    created = []
    skipped = []
    failed = {}

    person_dirs = _seed_person_dirs(seed_dir)
    if person_dirs:
        for index, person_dir in enumerate(person_dirs):
            try:
                nim, name = parse_seed_identity(
                    person_dir.name,
                    demo_nim=_demo_nim(index) if auto_demo_nim else None,
                )
                if name in existing_names:
                    skipped.append(name)
                    continue
                frames = [read_image(path) for path in _seed_image_paths(person_dir)]
                result = build_seed_embedding_from_frames(frames, palm_processor)
                db.add_user(
                    name,
                    result.embedding,
                    nim=nim,
                    individual_embeddings=result.individual_embeddings,
                    embedding_hands=["unknown"] * len(result.individual_embeddings),
                )
                created.append(name)
                existing_names.add(name)
            except Exception as exc:
                failed[person_dir.name] = str(exc)

        return SeedUsersSummary(created=created, skipped=skipped, failed=failed)

    for index, path in enumerate(_seed_image_paths(seed_dir)):
        try:
            nim, name = parse_seed_identity(
                path.stem,
                demo_nim=_demo_nim(index) if auto_demo_nim else None,
            )
            if name in existing_names:
                skipped.append(name)
                continue
            frame = read_image(path)
            result = build_seed_embedding(frame, palm_processor)
            db.add_user(
                name,
                result.embedding,
                nim=nim,
                individual_embeddings=result.individual_embeddings,
                embedding_hands=["unknown"] * len(result.individual_embeddings),
            )
            created.append(name)
            existing_names.add(name)
        except Exception as exc:
            failed[path.stem] = str(exc)

    return SeedUsersSummary(created=created, skipped=skipped, failed=failed)
