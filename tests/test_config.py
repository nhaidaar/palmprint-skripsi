import importlib
import json
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def skip_project_dotenv(monkeypatch):
    monkeypatch.setenv("PALMGATE_SKIP_DOTENV", "1")


def test_device_runtime_env_overrides(monkeypatch):
    monkeypatch.setenv("DEVICE_RUNTIME_ENABLED", "1")
    monkeypatch.setenv("CAMERA_SOURCE", "usb")
    monkeypatch.setenv("CAMERA_DEVICE_PATH", "/dev/video0")
    monkeypatch.setenv("APP_HOST", "0.0.0.0")

    import app.config as config
    importlib.reload(config)

    assert config.DEVICE_RUNTIME_ENABLED is True
    assert config.CAMERA_SOURCE == "usb"
    assert config.CAMERA_DEVICE_PATH == "/dev/video0"
    assert config.APP_HOST == "0.0.0.0"


def test_usb_preview_interval_defaults_to_realtime(monkeypatch):
    monkeypatch.delenv("DEVICE_PREVIEW_FRAME_INTERVAL_MS", raising=False)

    import app.config as config
    importlib.reload(config)

    assert config.DEVICE_PREVIEW_FRAME_INTERVAL_MS == 33


def test_notebook_rembg_env_override(monkeypatch):
    monkeypatch.setenv("NOTEBOOK_REMBG_ENABLED", "0")

    import app.config as config
    importlib.reload(config)

    assert config.NOTEBOOK_REMBG_ENABLED is False


def test_lock_gpio_env_defaults_and_overrides(monkeypatch):
    monkeypatch.setenv("LOCK_GPIO_ENABLED", "1")
    monkeypatch.setenv("LOCK_GPIO_CHIP", "/dev/gpiochip2")
    monkeypatch.setenv("LOCK_GPIO_LINE", "42")
    monkeypatch.setenv("LOCK_ACTIVE_LOW", "0")
    monkeypatch.setenv("LOCK_UNLOCK_MS", "2500")

    import app.config as config
    importlib.reload(config)

    assert config.LOCK_GPIO_ENABLED is True
    assert config.LOCK_GPIO_CHIP == "/dev/gpiochip2"
    assert config.LOCK_GPIO_LINE == "42"
    assert config.LOCK_ACTIVE_LOW is False
    assert config.LOCK_UNLOCK_MS == 2500


def test_embedding_model_defaults(monkeypatch):
    monkeypatch.delenv("MODEL_PATH", raising=False)
    monkeypatch.delenv("MODEL_VERSION", raising=False)
    monkeypatch.delenv("MODEL_METADATA_PATH", raising=False)
    monkeypatch.delenv("SIMILARITY_THRESHOLD", raising=False)
    monkeypatch.delenv("EMBEDDING_DIM", raising=False)
    monkeypatch.delenv("ENROLLMENT_TTA_ENABLED", raising=False)
    monkeypatch.delenv("RECOGNITION_TTA_ENABLED", raising=False)

    import app.config as config
    importlib.reload(config)

    assert config.MODEL_VERSION == "final"
    assert config.MODEL_PATH == config.BASE_DIR / "models" / "final" / "model.tflite"
    assert config.MODEL_METADATA_PATH == config.BASE_DIR / "models" / "final" / "model_metadata.json"
    assert config.EMBEDDING_DIM == 128
    assert config.SIMILARITY_THRESHOLD == 0.7736719250679016
    assert config.TTA_ROTATIONS == (0.0, -6.0, 6.0)
    assert config.ENROLLMENT_TTA_ENABLED is True
    assert config.RECOGNITION_TTA_ENABLED is False


def test_dotenv_loader_sets_missing_env_without_overriding(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MODEL_VERSION=from_env_file\n"
        "MODEL_PATH=/tmp/from-env.tflite\n"
        "IGNORED_LINE\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MODEL_VERSION", raising=False)
    monkeypatch.setenv("MODEL_PATH", "/already-set.tflite")

    import app.config as config
    config._load_env_file(env_file)

    assert os.environ["MODEL_VERSION"] == "from_env_file"
    assert os.environ["MODEL_PATH"] == "/already-set.tflite"


def test_dotenv_loader_ignores_read_errors(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("MODEL_VERSION=from_file\n", encoding="utf-8")

    import app.config as config

    original_read_text = Path.read_text

    def read_text(path, *args, **kwargs):
        if path == env_file:
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    config._load_env_file(env_file)


def test_env_example_documents_default_model_version(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_root = Path(__file__).resolve().parent.parent
    env_example = (project_root / ".env.example").read_text()

    assert "MODEL_VERSION=final" in env_example
    assert "MODEL_PATH=" in env_example


def test_final_model_metadata_matches_notebook_pipeline():
    project_root = Path(__file__).resolve().parent.parent
    metadata = json.loads((project_root / "models" / "final" / "model_metadata.json").read_text())

    assert metadata["embedding_dim"] == 128
    assert metadata["operating_threshold"] == 0.7736719250679016
    assert metadata["tta_rotations"] == [0.0, -6.0, 6.0]
    assert "GaussianBlur(5x5)" in metadata["preprocessing"]


def test_model_version_env_uses_versioned_model_folder(monkeypatch):
    monkeypatch.delenv("MODEL_PATH", raising=False)
    monkeypatch.delenv("MODEL_METADATA_PATH", raising=False)
    monkeypatch.setenv("MODEL_VERSION", "embedding")

    import app.config as config
    importlib.reload(config)

    assert config.MODEL_PATH == config.BASE_DIR / "models" / "embedding" / "model.tflite"
    assert config.MODEL_METADATA_PATH == config.BASE_DIR / "models" / "embedding" / "model_metadata.json"


def test_model_path_env_overrides_model_version(tmp_path, monkeypatch):
    explicit_model = tmp_path / "custom.tflite"
    monkeypatch.setenv("MODEL_PATH", str(explicit_model))
    monkeypatch.setenv("MODEL_VERSION", "embedding")

    import app.config as config
    importlib.reload(config)

    assert config.MODEL_PATH == explicit_model


def test_model_metadata_overrides_threshold_and_dim(tmp_path, monkeypatch):
    metadata = tmp_path / "model_metadata.json"
    metadata.write_text(
        '{"embedding_dim": 64, "operating_threshold": 0.8123, "tta_rotations": [0, -3, 3]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_METADATA_PATH", str(metadata))
    monkeypatch.delenv("SIMILARITY_THRESHOLD", raising=False)
    monkeypatch.delenv("EMBEDDING_DIM", raising=False)

    import app.config as config
    importlib.reload(config)

    assert config.EMBEDDING_DIM == 64
    assert config.SIMILARITY_THRESHOLD == 0.8123
    assert config.TTA_ROTATIONS == (0.0, -3.0, 3.0)


def test_app_env_defaults_to_production(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)

    import app.config as config
    importlib.reload(config)

    assert config.APP_ENV == "production"
    assert config.DEV_FEATURES_ENABLED is False


def test_app_env_development_enables_dev_features(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")

    import app.config as config
    importlib.reload(config)

    assert config.APP_ENV == "development"
    assert config.DEV_FEATURES_ENABLED is True


def test_invalid_app_env_falls_back_to_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")

    import app.config as config
    importlib.reload(config)

    assert config.APP_ENV == "production"
    assert config.DEV_FEATURES_ENABLED is False
