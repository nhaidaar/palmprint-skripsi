from fastapi import APIRouter

from app.config import (
    APP_DEBUG,
    APP_ENV,
    CAMERA_SOURCE,
    DB_PATH,
    DEVICE_RUNTIME_ENABLED,
    DEV_FEATURES_ENABLED,
    LOCK_GPIO_ENABLED,
    PALMGATE_VERSION,
)

router = APIRouter()


def _device_status(row, device_runtime):
    device = row or {
        "worker_state": "disabled",
        "camera_connected": 0,
        "last_error": None,
        "fps": None,
        "last_inference_ms": None,
        "last_recognition_at": None,
    }
    if device_runtime is not None:
        session = device_runtime.registration_session
        device = {
            **device,
            "worker_state": "error" if device.get("last_error") else device_runtime.worker_state,
            "registration_active": session is not None,
            "registration_session_id": session.id if session else None,
            "registration_sample_index": session.current_sample_index if session else None,
            "registration_captured_count": len(session.captured_samples) if session else 0,
            "scan_state": getattr(device_runtime, "scan_state", None),
        }
    else:
        device = {
            **device,
            "registration_active": False,
            "registration_session_id": None,
            "registration_sample_index": None,
            "registration_captured_count": 0,
            "scan_state": None,
        }
    return device


@router.get("/api/status")
async def status():
    from app.main import db, device_runtime, exit_device_runtime

    entry = _device_status(db.get_device_status() if db and DEVICE_RUNTIME_ENABLED else None, device_runtime)
    exit = _device_status(db.get_device_status("EXIT") if db and DEVICE_RUNTIME_ENABLED else None, exit_device_runtime)
    return {
        "app": {
            "mode": "debug" if APP_DEBUG else "non-debug",
            "debug": APP_DEBUG,
            "gpio_enabled": LOCK_GPIO_ENABLED,
            "version": PALMGATE_VERSION,
            "environment": APP_ENV,
            "dev_features": DEV_FEATURES_ENABLED,
            "camera_source": CAMERA_SOURCE,
            "device_runtime_enabled": DEVICE_RUNTIME_ENABLED,
        },
        "database": {"path": str(DB_PATH)},
        "device": entry,
        "devices": {"ENTRY": entry, "EXIT": exit},
    }
