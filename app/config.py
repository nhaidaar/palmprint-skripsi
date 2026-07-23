import logging
import math
import os
from pathlib import Path

log = logging.getLogger("palmgate.config")

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("Could not read env file %s: %s", path, exc)
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


if os.getenv("PALMGATE_SKIP_DOTENV", "0") != "1":
    _load_env_file(BASE_DIR / ".env")

DEFAULT_SIMILARITY_THRESHOLD = 0.75
EMBEDDING_DIM = 128
TTA_ROTATIONS = (0.0, -6.0, 6.0)
HAND_LANDMARKER_PATH = BASE_DIR / "hand_landmarker.task"

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
if APP_ENV not in {"development", "production"}:
    APP_ENV = "production"
DEV_FEATURES_ENABLED = APP_ENV == "development"
PALMGATE_VERSION = os.getenv("PALMGATE_VERSION", "local").strip() or "local"

# DB_PATH can be overridden via environment variable for Docker deployments
# e.g. DB_PATH=/data/palmprint.db → mount a named volume at /data
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "palmprint.db")))

DEVICE_RUNTIME_ENABLED = os.getenv("DEVICE_RUNTIME_ENABLED", "0") == "1"
CAMERA_SOURCE = os.getenv("CAMERA_SOURCE", "browser")
CAMERA_DEVICE_PATH = os.getenv("CAMERA_DEVICE_PATH", "/dev/video0")
DEVICE_FRAME_INTERVAL_MS = int(os.getenv("DEVICE_FRAME_INTERVAL_MS", "250"))
DEVICE_PREVIEW_FRAME_INTERVAL_MS = int(os.getenv("DEVICE_PREVIEW_FRAME_INTERVAL_MS", "33"))
DEVICE_HOLD_MS = int(os.getenv("DEVICE_HOLD_MS", "1200"))
DEVICE_COOLDOWN_MS = int(os.getenv("DEVICE_COOLDOWN_MS", "3000"))
DEVICE_STATUS_HEARTBEAT_MS = int(os.getenv("DEVICE_STATUS_HEARTBEAT_MS", "1000"))
LOCK_GPIO_ENABLED = os.getenv("LOCK_GPIO_ENABLED", "0") == "1"
LOCK_GPIO_CHIP = os.getenv("LOCK_GPIO_CHIP", "/dev/gpiochip0")
LOCK_GPIO_LINE = os.getenv("LOCK_GPIO_LINE", "75")
LOCK_ACTIVE_LOW = os.getenv("LOCK_ACTIVE_LOW", "1") == "1"
LOCK_UNLOCK_MS = int(os.getenv("LOCK_UNLOCK_MS", "2000"))

def _read_threshold(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric and between 0 and 1") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


SIMILARITY_THRESHOLD = _read_threshold(
    "SIMILARITY_THRESHOLD",
    DEFAULT_SIMILARITY_THRESHOLD,
)
DUPLICATE_THRESHOLD = _read_threshold(
    "DUPLICATE_THRESHOLD",
    SIMILARITY_THRESHOLD,
)

REGISTRATION_HANDS = ("left", "right")
REGISTRATION_CAPTURES_PER_HAND = 5
REGISTRATION_TOTAL_CAPTURES = REGISTRATION_CAPTURES_PER_HAND * len(REGISTRATION_HANDS)
REGISTRATION_STORE_EMBEDDINGS_PER_HAND = REGISTRATION_CAPTURES_PER_HAND
REGISTRATION_MIN_VALID_PER_HAND = 5
REGISTRATION_CAPTURES = REGISTRATION_TOTAL_CAPTURES
USB_REGISTRATION_CAPTURES = REGISTRATION_TOTAL_CAPTURES
USB_REGISTRATION_STORE_EMBEDDINGS = REGISTRATION_STORE_EMBEDDINGS_PER_HAND
USB_REGISTRATION_MIN_VALID = REGISTRATION_MIN_VALID_PER_HAND
USB_REGISTRATION_MIN_BLUR = 70.0
USB_REGISTRATION_MIN_BRIGHTNESS = 45.0
USB_REGISTRATION_MAX_BRIGHTNESS = 220.0

IMG_SIZE = (224, 224)
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID = (8, 8)
MIN_PALM_WIDTH = 40.0
PALM_ROI_SCALE = 1.5
