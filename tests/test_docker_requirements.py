from pathlib import Path


def test_docker_requirements_use_active_runtime_dependencies():
    requirements = Path("requirements.docker.txt").read_text()
    desktop_requirements = Path("requirements.txt").read_text()

    assert "mediapipe" in requirements
    assert "opencv-python-headless" in requirements
    assert "tflite-runtime" in requirements
    assert "gpiod" in requirements
    assert "openpyxl==3.1.*" in requirements
    assert "openpyxl==3.1.*" in desktop_requirements
    assert "rembg" not in requirements
    assert "onnxruntime" not in requirements


def test_dockerfile_pins_bookworm_base_for_gpio_runtime_libs():
    dockerfile = Path("Dockerfile").read_text()

    assert "FROM python:3.11-slim-bookworm AS builder" in dockerfile
    assert "FROM python:3.11-slim-bookworm\n" in dockerfile
    assert "libgpiod2" in dockerfile


def test_dockerfile_uses_uv_for_python_dependencies():
    dockerfile = Path("Dockerfile").read_text()

    assert "COPY --from=ghcr.io/astral-sh/uv:" in dockerfile
    assert "COPY --from=ghcr.io/astral-sh/uv:latest" not in dockerfile
    assert "uv pip install --system --no-cache-dir -r requirements.docker.txt" in dockerfile
    assert "RUN pip install --no-cache-dir -r requirements.docker.txt" not in dockerfile


def test_compose_passes_dotenv_values_to_palmgate_container():
    compose = Path("docker-compose.yml").read_text()
    common = compose[compose.index("x-palmgate-common:") : compose.index("x-cloudflared-common:")]

    assert "env_file:" in common
    assert "- .env" in common


def test_compose_does_not_configure_old_notebook_rembg_path():
    compose = Path("docker-compose.yml").read_text()

    assert "NOTEBOOK_REMBG" not in compose


def test_env_example_selects_usb_compose_profile_by_default():
    env_example = Path(".env.example").read_text()

    assert "COMPOSE_PROFILES=usb" in env_example
    assert "DEVICE_RUNTIME_ENABLED=1" in env_example
    assert "CAMERA_SOURCE=usb" in env_example
    assert "CAMERA_DEVICE_PATH=/dev/video0" in env_example
    assert "PALMGATE_MODELS_DIR=./models" in env_example
    assert "LOCK_GPIO_ENABLED=0" in env_example
    assert "LOCK_GPIO_LINE=75" in env_example
    assert "LOCK_ACTIVE_LOW=1" in env_example
    assert "LOCK_UNLOCK_MS=2000" in env_example


def test_readme_documents_prebuilt_image_update_flow():
    readme = Path("README.md").read_text()

    assert "cp .env.example .env" in readme
    assert "docker compose pull" in readme
    assert "docker compose up -d" in readme
    assert "docker compose up --build" not in readme


def test_usb_compose_uses_configurable_camera_device_path():
    compose = Path("docker-compose.yml").read_text()

    assert "CAMERA_SOURCE=usb" in compose
    assert "CAMERA_DEVICE_PATH=${CAMERA_DEVICE_PATH:-/dev/video0}" in compose
    assert "${CAMERA_DEVICE_PATH:-/dev/video0}:${CAMERA_DEVICE_PATH:-/dev/video0}" in compose
    assert "usb-046d_C270_HD_WEBCAM" not in compose


def test_usb_compose_maps_gpiochip_for_lock_relay():
    compose = Path("docker-compose.yml").read_text()

    assert "LOCK_GPIO_ENABLED=${LOCK_GPIO_ENABLED:-0}" in compose
    assert "LOCK_GPIO_CHIP=${LOCK_GPIO_CHIP:-/dev/gpiochip0}" in compose
    assert "LOCK_GPIO_LINE=${LOCK_GPIO_LINE:-75}" in compose
    assert "LOCK_ACTIVE_LOW=${LOCK_ACTIVE_LOW:-1}" in compose
    assert "LOCK_UNLOCK_MS=${LOCK_UNLOCK_MS:-2000}" in compose
    assert "${LOCK_GPIO_CHIP:-/dev/gpiochip0}:${LOCK_GPIO_CHIP:-/dev/gpiochip0}" in compose


def test_usb_compose_uses_separate_preview_and_processing_intervals():
    compose = Path("docker-compose.yml").read_text()

    assert "DEVICE_PREVIEW_FRAME_INTERVAL_MS=33" in compose
    assert "DEVICE_FRAME_INTERVAL_MS=250" in compose
    assert "DEVICE_FRAME_INTERVAL_MS=1000" not in compose


def test_compose_mounts_selected_model_version_from_project_models():
    compose = Path("docker-compose.yml").read_text()

    assert "${PALMGATE_MODELS_DIR:-./models}/${MODEL_VERSION:-final}:/app/models/${MODEL_VERSION:-final}:ro" in compose
    assert "MODEL_VERSION=${MODEL_VERSION:-final}" in compose
    assert "./models/embedding:/app/models/embedding:ro" not in compose
    assert "./palm_embedding.tflite:/app/palm_embedding.tflite" not in compose
    assert "palm_recognition.tflite:/app/palm_recognition.tflite" not in compose


def test_dockerfile_stamps_palmgate_version():
    dockerfile = Path("Dockerfile").read_text()

    assert "ARG PALMGATE_VERSION=local" in dockerfile
    assert "ENV PALMGATE_VERSION=${PALMGATE_VERSION}" in dockerfile


def test_compose_uses_prebuilt_ghcr_image_by_default():
    compose = Path("docker-compose.yml").read_text()
    common = compose[compose.index("x-palmgate-common:") : compose.index("x-cloudflared-common:")]

    assert "image: ${PALMGATE_IMAGE:-ghcr.io/nhaidaar/palmprint-be:latest}" in common
    assert "build:" not in common


def test_env_example_documents_palmgate_image():
    env_example = Path(".env.example").read_text()

    assert "PALMGATE_IMAGE=ghcr.io/nhaidaar/palmprint-be:latest" in env_example


def test_github_actions_publishes_ghcr_image_with_version_arg():
    workflow = Path(".github/workflows/docker.yml").read_text()

    assert "ghcr.io/nhaidaar/palmprint-be" in workflow
    assert "SHORT_SHA=${GITHUB_SHA::7}" in workflow
    assert "PALMGATE_VERSION=${{ env.SHORT_SHA }}" in workflow
    assert "docker/setup-qemu-action@v3" in workflow
    assert "docker/build-push-action@v6" in workflow
    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "packages: write" in workflow
    assert "- master" in workflow
