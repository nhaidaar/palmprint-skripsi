import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def skip_project_dotenv(monkeypatch):
    monkeypatch.setenv("PALMGATE_SKIP_DOTENV", "1")


def import_config_with_threshold(raw_value: str):
    env = os.environ.copy()
    env["PALMGATE_SKIP_DOTENV"] = "1"
    env["SIMILARITY_THRESHOLD"] = raw_value
    return subprocess.run(
        [sys.executable, "-c", "import app.config; print(app.config.SIMILARITY_THRESHOLD)"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def import_config_with_duplicate_threshold(raw_value: str | None, similarity: str = "0.75"):
    env = os.environ.copy()
    env["PALMGATE_SKIP_DOTENV"] = "1"
    env["SIMILARITY_THRESHOLD"] = similarity
    if raw_value is None:
        env.pop("DUPLICATE_THRESHOLD", None)
    else:
        env["DUPLICATE_THRESHOLD"] = raw_value
    return subprocess.run(
        [sys.executable, "-c", "import app.config; print(app.config.DUPLICATE_THRESHOLD)"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


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


def test_notebook_runtime_config_is_removed():
    import app.config as config

    assert not hasattr(config, "NOTEBOOK_REMBG_ENABLED")
    assert not hasattr(config, "NOTEBOOK_REMBG_MODEL")


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


def test_embedding_contract_is_fixed(monkeypatch):
    monkeypatch.delenv("SIMILARITY_THRESHOLD", raising=False)

    import app.config as config
    importlib.reload(config)

    assert config.DEFAULT_SIMILARITY_THRESHOLD == 0.75
    assert config.SIMILARITY_THRESHOLD == 0.75
    assert config.EMBEDDING_DIM == 128
    assert config.TTA_ROTATIONS == (0.0, -6.0, 6.0)

    retired_names = (
        "DEFAULT_MODEL_VERSION",
        "DEFAULT_MODEL_DIR",
        "DEFAULT_MODEL_FILENAME",
        "VERSIONED_MODEL_FILENAME",
        "DEFAULT_MODEL_METADATA_FILENAME",
        "DEFAULT_EMBEDDING_DIM",
        "DEFAULT_TTA_ROTATIONS",
        "MODEL_VERSION",
        "MODEL_DIR",
        "MODEL_PATH",
        "MODEL_METADATA_PATH",
        "MODEL_METADATA",
        "_load_model_metadata",
    )
    for name in retired_names:
        assert not hasattr(config, name)


def test_tta_enable_flags_are_removed():
    import app.config as config

    assert not hasattr(config, "ENROLLMENT_TTA_ENABLED")
    assert not hasattr(config, "RECOGNITION_TTA_ENABLED")


def test_similarity_threshold_env_override():
    result = import_config_with_threshold("0.82")

    assert result.returncode == 0
    assert result.stdout.strip() == "0.82"


@pytest.mark.parametrize(("raw_value", "expected"), (("0", "0.0"), ("1", "1.0")))
def test_similarity_threshold_accepts_inclusive_boundaries(raw_value, expected):
    result = import_config_with_threshold(raw_value)

    assert result.returncode == 0
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "raw_value",
    ("not-a-number", "-0.01", "1.01", "nan", "inf", "-inf"),
)
def test_invalid_similarity_threshold_raises_value_error(raw_value):
    result = import_config_with_threshold(raw_value)

    assert result.returncode != 0
    assert "SIMILARITY_THRESHOLD" in result.stderr


def test_duplicate_threshold_defaults_to_similarity_threshold():
    result = import_config_with_duplicate_threshold(None, similarity="0.82")

    assert result.returncode == 0
    assert result.stdout.strip() == "0.82"


@pytest.mark.parametrize(("raw_value", "expected"), (("0", "0.0"), ("1", "1.0")))
def test_duplicate_threshold_accepts_inclusive_boundaries(raw_value, expected):
    result = import_config_with_duplicate_threshold(raw_value)

    assert result.returncode == 0
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "raw_value",
    ("not-a-number", "-0.01", "1.01", "nan", "inf", "-inf"),
)
def test_invalid_duplicate_threshold_raises_value_error(raw_value):
    result = import_config_with_duplicate_threshold(raw_value)

    assert result.returncode != 0
    assert "DUPLICATE_THRESHOLD" in result.stderr


def test_dotenv_loader_sets_missing_env_without_overriding(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_HOST=from_env_file\n"
        "DB_PATH=/tmp/from-env.db\n"
        "IGNORED_LINE\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.setenv("DB_PATH", "/already-set.db")

    import app.config as config
    config._load_env_file(env_file)

    assert os.environ["APP_HOST"] == "from_env_file"
    assert os.environ["DB_PATH"] == "/already-set.db"


def test_dotenv_loader_ignores_read_errors(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_HOST=from_file\n", encoding="utf-8")

    import app.config as config

    original_read_text = Path.read_text

    def read_text(path, *args, **kwargs):
        if path == env_file:
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    config._load_env_file(env_file)


def test_historical_final_model_metadata_matches_export_contract():
    metadata_path = PROJECT_ROOT / "models" / "final" / "model_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert metadata["embedding_dim"] == 128
    assert metadata["tta_rotations"] == [0.0, -6.0, 6.0]
    assert metadata["operating_threshold"] == pytest.approx(0.7736719250679016)


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
