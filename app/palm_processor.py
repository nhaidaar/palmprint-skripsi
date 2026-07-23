import logging
import threading
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

from app.config import (
    CLAHE_CLIP_LIMIT,
    CLAHE_TILE_GRID,
    EMBEDDING_DIM,
    HAND_LANDMARKER_PATH,
    IMG_SIZE,
    MIN_PALM_WIDTH,
    PALM_ROI_SCALE,
    TTA_ROTATIONS,
)

MODEL_PATH = Path(__file__).resolve().parent.parent / "model.tflite"

log = logging.getLogger("palmgate")
log.setLevel(logging.INFO)
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    log.addHandler(handler)
log.propagate = True

# MediaPipe hand landmark indices (same as legacy API)
WRIST = 0
INDEX_FINGER_MCP = 5
MIDDLE_FINGER_MCP = 9
PINKY_MCP = 17


class PalmProcessor:
    def __init__(self, hand_model_path=HAND_LANDMARKER_PATH):
        self.clahe = cv2.createCLAHE(
            clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID
        )
        self.interpreter = None
        self._input_index = None
        self._output_index = None
        self._hand_landmarker = None
        self._operation_lock = threading.RLock()

        if hand_model_path is not None:
            self._load_hand_model(hand_model_path)
        self._load_model(MODEL_PATH)

    def _load_hand_model(self, hand_model_path):
        options = mp_vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(hand_model_path)),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_hands=1,
            # Lower thresholds to handle float16 model variance and webcam conditions
            min_hand_detection_confidence=0.3,
            min_hand_presence_confidence=0.3,
        )
        self._hand_landmarker = mp_vision.HandLandmarker.create_from_options(options)

    def _load_model(self, model_path: Path):
        if not model_path.is_file():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        try:
            try:
                from tflite_runtime.interpreter import Interpreter
            except ImportError:
                import tensorflow as tf

                Interpreter = tf.lite.Interpreter

            try:
                interpreter = Interpreter(model_path=str(model_path), num_threads=4)
            except TypeError:
                interpreter = Interpreter(model_path=str(model_path))
            interpreter.allocate_tensors()
            input_details = interpreter.get_input_details()
            output_details = interpreter.get_output_details()
        except Exception as exc:
            raise RuntimeError(f"Unable to load TFLite model: {model_path}") from exc

        input_shape = tuple(int(value) for value in input_details[0]["shape"])
        if input_shape != (1, 224, 224, 3):
            raise ValueError(
                "Embedding model input shape must be (1, 224, 224, 3), "
                f"got {input_shape}"
            )
        if np.dtype(input_details[0]["dtype"]) != np.dtype(np.float32):
            raise ValueError(
                "Embedding model input dtype must be float32, "
                f"got {np.dtype(input_details[0]['dtype']).name}"
            )

        output_size = int(np.prod(output_details[0]["shape"]))
        if output_size != EMBEDDING_DIM:
            raise ValueError(
                f"Embedding model must output exactly {EMBEDDING_DIM} values, got {output_size}"
            )
        if np.dtype(output_details[0]["dtype"]) != np.dtype(np.float32):
            raise ValueError(
                "Embedding model output dtype must be float32, "
                f"got {np.dtype(output_details[0]['dtype']).name}"
            )

        self.interpreter = interpreter
        self._input_index = input_details[0]["index"]
        self._output_index = output_details[0]["index"]
        log.info("MODEL | embedding output index=%d dim=%d", self._output_index, EMBEDDING_DIM)

    def extract_palm_roi(self, frame_rgb: np.ndarray):
        if self._hand_landmarker is None:
            log.warning("DETECT | hand_landmarker not loaded")
            return None

        h, w = frame_rgb.shape[:2]
        log.debug("DETECT | image received  shape=%s  dtype=%s  min=%d  max=%d",
                  frame_rgb.shape, frame_rgb.dtype,
                  int(frame_rgb.min()), int(frame_rgb.max()))

        # Reject clearly broken frames (all-black or all-white)
        mean_brightness = float(frame_rgb.mean())
        log.debug("DETECT | mean brightness=%.1f", mean_brightness)
        if mean_brightness < 5:
            log.warning("DETECT | frame appears to be all-black — camera may not be ready")
            return None

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        with self._operation_lock:
            result = self._hand_landmarker.detect(mp_image)

        if not result.hand_landmarks:
            log.warning(
                "DETECT | no hand found  (image %dx%d, brightness=%.1f)"
                " — try: hold palm flat, fill ~50%% of frame, good lighting",
                w, h, mean_brightness,
            )
            return None

        log.info("DETECT | hand found  hands=%d  landmarks=%d",
                 len(result.hand_landmarks), len(result.hand_landmarks[0]))

        landmarks = result.hand_landmarks[0]

        wrist = landmarks[WRIST]
        index_mcp = landmarks[INDEX_FINGER_MCP]
        pinky_mcp = landmarks[PINKY_MCP]
        middle_mcp = landmarks[MIDDLE_FINGER_MCP]

        log.debug("DETECT | wrist=(%.3f,%.3f)  index_mcp=(%.3f,%.3f)"
                  "  pinky_mcp=(%.3f,%.3f)  middle_mcp=(%.3f,%.3f)",
                  wrist.x, wrist.y,
                  index_mcp.x, index_mcp.y,
                  pinky_mcp.x, pinky_mcp.y,
                  middle_mcp.x, middle_mcp.y)

        def _point(index):
            landmark = landmarks[index]
            return np.array([landmark.x * w, landmark.y * h], dtype=np.float32)

        wrist_pt = _point(WRIST)
        index_pt = _point(INDEX_FINGER_MCP)
        middle_pt = _point(MIDDLE_FINGER_MCP)
        pinky_pt = _point(PINKY_MCP)

        palm_width = float(np.linalg.norm(index_pt - pinky_pt))
        if palm_width < MIN_PALM_WIDTH:
            log.warning("DETECT | palm too small width=%.1fpx", palm_width)
            return None

        angle = float(np.degrees(np.arctan2(pinky_pt[1] - index_pt[1], pinky_pt[0] - index_pt[0])))
        if angle > 90.0:
            angle -= 180.0
        elif angle < -90.0:
            angle += 180.0
        center = (wrist_pt + middle_pt) / 2.0
        rotation = cv2.getRotationMatrix2D((float(center[0]), float(center[1])), angle, 1.0)
        rotated = cv2.warpAffine(frame_rgb, rotation, (w, h), flags=cv2.INTER_LINEAR)

        half = (palm_width * PALM_ROI_SCALE) / 2.0
        cx, cy = float(center[0]), float(center[1])
        x1, y1 = int(max(0, cx - half)), int(max(0, cy - half))
        x2, y2 = int(min(w, cx + half)), int(min(h, cy + half))

        log.debug(
            "DETECT | palm_width=%.1fpx angle=%.1f center=(%.1f,%.1f) box=[%d:%d, %d:%d]",
            palm_width,
            angle,
            cx,
            cy,
            y1,
            y2,
            x1,
            x2,
        )

        roi = rotated[y1:y2, x1:x2]
        if roi.size == 0:
            log.warning("DETECT | ROI is empty after crop — hand may be at image edge")
            return None

        log.info("DETECT | ROI extracted  shape=%s", roi.shape)
        return roi

    def apply_clahe(self, gray_img: np.ndarray) -> np.ndarray:
        return self.clahe.apply(gray_img)

    def preprocess_roi(self, roi: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        enhanced = self.apply_clahe(blurred)
        rgb = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)
        resized = cv2.resize(rgb, IMG_SIZE, interpolation=cv2.INTER_CUBIC)
        return resized.astype(np.float32)

    def extract_embedding_from_frame(
        self, frame_rgb: np.ndarray
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        with self._operation_lock:
            roi = self.extract_palm_roi(frame_rgb)
            if roi is None:
                return None, None

            model_input = self.preprocess_roi(roi)
            return self._infer_embedding(model_input), model_input

    def extract_embedding_from_roi(
        self, roi_rgb: np.ndarray
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        with self._operation_lock:
            if roi_rgb is None or roi_rgb.size == 0:
                return None, None

            model_input = self.preprocess_roi(roi_rgb)
            return self._infer_embedding(model_input), model_input

    def _infer_embedding(self, model_input: np.ndarray) -> np.ndarray:
        if self.interpreter is None:
            raise RuntimeError("TFLite model not loaded")
        if self._input_index is None or self._output_index is None:
            raise RuntimeError("TFLite tensor indices are not initialized")

        embeddings = []
        for angle in TTA_ROTATIONS:
            rotated_input = self._rotate_model_input(model_input, angle)
            input_data = np.expand_dims(rotated_input.astype(np.float32), axis=0)
            self.interpreter.set_tensor(self._input_index, input_data)
            self.interpreter.invoke()
            output = np.asarray(
                self.interpreter.get_tensor(self._output_index), dtype=np.float32
            ).reshape(-1)

            if output.size != EMBEDDING_DIM:
                raise ValueError(
                    f"Embedding model must output exactly {EMBEDDING_DIM} values, got {output.size}"
                )
            output_norm = float(np.linalg.norm(output))
            if (
                not np.all(np.isfinite(output))
                or not np.isfinite(output_norm)
                or output_norm <= np.finfo(np.float32).eps
            ):
                raise ValueError("Embedding model output must be finite non-zero values")

            embeddings.append(self._normalize_embedding(output))

        mean_embedding = np.mean(embeddings, axis=0)
        mean_norm = float(np.linalg.norm(mean_embedding))
        if (
            not np.all(np.isfinite(mean_embedding))
            or not np.isfinite(mean_norm)
            or mean_norm <= np.finfo(np.float32).eps
        ):
            raise ValueError("Averaged embedding must be finite non-zero values")
        return self._normalize_embedding(mean_embedding)

    def get_registration_guidance_metrics(self, frame_rgb: np.ndarray, previous_metrics: dict | None = None):
        gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
        base = {
            "hand_detected": False,
            "hand_clipped": True,
            "height_ratio": 0.0,
            "rotation_degrees": 999.0,
            "center_x_ratio": 0.0,
            "brightness": float(gray.mean()),
            "blur_score": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
            "steady": False,
        }
        if self._hand_landmarker is None:
            return base

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        with self._operation_lock:
            result = self._hand_landmarker.detect(mp_image)
        if not result.hand_landmarks:
            return base

        landmarks = result.hand_landmarks[0]
        xs = [lm.x for lm in landmarks]
        ys = [lm.y for lm in landmarks]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        h, w = gray.shape[:2]
        pad_x = int((max_x - min_x) * w * 0.12)
        pad_y = int((max_y - min_y) * h * 0.12)
        x1 = max(0, int(min_x * w) - pad_x)
        y1 = max(0, int(min_y * h) - pad_y)
        x2 = min(w, int(max_x * w) + pad_x)
        y2 = min(h, int(max_y * h) + pad_y)
        hand_gray = gray[y1:y2, x1:x2]
        if hand_gray.size:
            brightness = float(hand_gray.mean())
            blur_score = float(cv2.Laplacian(hand_gray, cv2.CV_64F).var())
        else:
            brightness = base["brightness"]
            blur_score = base["blur_score"]

        index_mcp = landmarks[INDEX_FINGER_MCP]
        pinky_mcp = landmarks[PINKY_MCP]
        rotation_degrees = float(
            np.degrees(np.arctan2(pinky_mcp.y - index_mcp.y, pinky_mcp.x - index_mcp.x))
        )

        metrics = {
            "hand_detected": True,
            "hand_clipped": min_x < 0.03 or max_x > 0.97 or min_y < 0.03 or max_y > 0.97,
            "height_ratio": float(max_y - min_y),
            "rotation_degrees": rotation_degrees,
            "center_x_ratio": float((min_x + max_x) / 2),
            "brightness": brightness,
            "blur_score": blur_score,
            "steady": False,
        }
        if previous_metrics and previous_metrics.get("hand_detected"):
            metrics["steady"] = (
                abs(metrics["center_x_ratio"] - previous_metrics.get("center_x_ratio", 0.0)) <= 0.03
                and abs(metrics["height_ratio"] - previous_metrics.get("height_ratio", 0.0)) <= 0.04
                and abs(metrics["rotation_degrees"] - previous_metrics.get("rotation_degrees", 999.0)) <= 4.0
            )
        return metrics

    def _normalize_embedding(self, embedding: np.ndarray) -> np.ndarray:
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            return vector
        return (vector / norm).astype(np.float32)

    def _rotate_model_input(self, model_input: np.ndarray, angle_degrees: float) -> np.ndarray:
        if abs(angle_degrees) < 1e-6:
            return model_input
        h, w = model_input.shape[:2]
        matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle_degrees, 1.0)
        return cv2.warpAffine(
            model_input,
            matrix,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0),
        ).astype(np.float32)

    def compute_similarity(self, embedding: np.ndarray, stored_embeddings: list, threshold: float) -> dict:
        if not stored_embeddings:
            return {
                "status": "DENIED",
                "name": "Unknown",
                "similarity": 0.0,
                "closest_match": None,
                "user_id": None,
            }

        query = self._normalize_embedding(embedding)
        best_score = -1.0
        best_match = None
        best_user_id = None

        for entry in stored_embeddings:
            stored = np.asarray(entry["embedding"], dtype=np.float32).reshape(-1)
            if stored.shape != query.shape:
                log.warning(
                    "MATCH | skipped incompatible embedding dim stored=%d query=%d user=%s",
                    stored.shape[0],
                    query.shape[0],
                    entry.get("name"),
                )
                continue
            stored = self._normalize_embedding(stored)
            score = float(np.dot(query, stored))
            if score > best_score:
                best_score = score
                best_match = entry["name"]
                best_user_id = entry["id"]

        if best_score < 0.0:
            return {
                "status": "DENIED",
                "name": "Unknown",
                "similarity": 0.0,
                "closest_match": None,
                "user_id": None,
            }

        if best_score >= threshold:
            return {
                "status": "ALLOWED",
                "name": best_match,
                "similarity": round(best_score, 4),
                "closest_match": best_match,
                "user_id": best_user_id,
            }

        return {
            "status": "DENIED",
            "name": "Unknown",
            "similarity": round(best_score, 4),
            "closest_match": best_match,
            "user_id": None,
        }

    def close(self):
        if self._hand_landmarker is not None:
            self._hand_landmarker.close()
