# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PalmGate is a palmprint recognition system for smart door locks. It runs in two modes:
- **Browser mode**: Web UI with phone/desktop camera for testing and registration
- **Device mode**: 24/7 USB camera worker on Orange Pi for production use

## Commands

```bash
# Run development server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Run frontend development server
cd frontend && bun run dev

# Run Docker browser deployment
PALMGATE_HTTP_PORT=8080 docker compose --profile browser up --build

# Run Docker USB deployment
PALMGATE_HTTP_PORT=8080 docker compose --profile usb up --build

# Run tests
python -m pytest tests/ -v

# Run device worker (Orange Pi with USB camera)
DEVICE_RUNTIME_ENABLED=1 CAMERA_SOURCE=usb CAMERA_DEVICE_PATH=/dev/video0 python -m app.device_runtime

# Seed users from images
python scripts/seed_users.py seeds
python scripts/seed_users.py seeds --replace-users  # replace existing
```

## Architecture

### Processing Pipeline

The active runtime preprocessing path is **MediaPipe ROI** (`palm_processor.py:extract_palm_roi`): hand landmarks → palm ROI crop → grayscale → Gaussian blur (5x5) → CLAHE → RGB → 224x224 resize.

The fixed root `model.tflite` runs for rotations `0`, `-6`, and `+6` degrees. Each 128-dimensional output is L2-normalized, the three embeddings are averaged, and the result is normalized again. Recognition uses cosine similarity against stored per-hand templates with `SIMILARITY_THRESHOLD`, which defaults to `0.75`.

### Multi-Embedding Storage

USB registration captures 5 samples per hand, stores one normalized template per hand, and recognition matches against the best hand template.

### Key Components

- `app/main.py`: FastAPI entry point, lifespan management
- `app/device_runtime.py`: USB camera worker with hold-to-scan and registration state machine
- `app/palm_processor.py`: MediaPipe detection, Gaussian blur and CLAHE enhancement, always-on TTA, TFLite inference
- `app/services/registration_quality.py`: 5 guidance targets per hand (center, closer, farther, rotate, shift)
- `app/database.py`: SQLite with users, user_embeddings, access_logs, device_status tables

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEVICE_RUNTIME_ENABLED` | `0` | Enable USB camera worker |
| `CAMERA_SOURCE` | `browser` | `browser` or `usb` |
| `CAMERA_DEVICE_PATH` | `/dev/video0` | Camera device path (e.g., `/dev/video0`, `/dev/video1`) |
| `DB_PATH` | `palmprint.db` | SQLite database location |
| `SIMILARITY_THRESHOLD` | `0.75` | Cosine-similarity threshold for recognition |

## Required Model Files

Place both runtime files in the project root:
- `model.tflite` - fixed palm embedding model
- `hand_landmarker.task` - MediaPipe hand detection model

## Database Migration

Embeddings are incompatible across preprocessing/model changes. After switching to the root `model.tflite`, stop PalmGate and re-register users after deleting the active database:
- local process: delete `palmprint.db`;
- Docker Compose: run `docker compose down -v` to remove `/data/palmprint.db` from the named volume.

Both resets delete users, embeddings, access logs, and persisted device status.

## Orange Pi Deployment

Systemd unit files are not included. Use the Docker Compose USB profile for the always-on API, frontend, device worker, and proxy.
