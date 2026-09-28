# PALMGATE — Palmprint Recognition Preview

Web-based palmprint recognition app that now supports two operating modes:
- **Browser mode** — use a phone or desktop browser camera for testing and registration
- **Device mode** — run two 24x7 USB-camera workers on an Orange Pi: ENTRY and EXIT

Both workers share one fixed palm recognition model, `model.tflite`, with no model selector. MediaPipe supplies the separate hand detector used to locate the palm.

## Requirements

- Python 3.10+
- `model.tflite` in the project root
- `hand_landmarker.task` in the project root
- Browser MediaPipe assets in `app/static/vendor/mediapipe/` for offline browser hand detection

## Setup

```bash
pip install -r requirements.txt
```

If `hand_landmarker.task` is missing:

```python
import urllib.request
urllib.request.urlretrieve(
    'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task',
    'hand_landmarker.task'
)
```

Browser hand detection does not load MediaPipe or fonts from a CDN at runtime. The browser assets are vendored under `app/static/vendor/mediapipe/` and copied into the React build by `frontend/scripts/sync-static-vendor.mjs`.

To refresh those browser assets while online:

```bash
python - <<'PY'
from pathlib import Path
from urllib.request import urlretrieve

root = Path('app/static/vendor/mediapipe')
files = {
    'vision_bundle.mjs': 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs',
    'wasm/vision_wasm_internal.js': 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm/vision_wasm_internal.js',
    'wasm/vision_wasm_internal.wasm': 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm/vision_wasm_internal.wasm',
    'wasm/vision_wasm_nosimd_internal.js': 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm/vision_wasm_nosimd_internal.js',
    'wasm/vision_wasm_nosimd_internal.wasm': 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm/vision_wasm_nosimd_internal.wasm',
    'hand_landmarker.task': 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task',
}

for relative_path, url in files.items():
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, target)
    print(target)
PY
cd frontend && bun run sync:static-vendor
```

## Run locally

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open: [http://127.0.0.1:8000](http://127.0.0.1:8000)

## Run with Docker

Use a 64-bit Linux image on the Orange Pi Zero 3 (`uname -m` should print `aarch64`). Docker Compose reads `.env`, not `.env.example`. The example defaults to two USB cameras. On the Orange Pi host, find their capture nodes:

```bash
sudo apt-get install v4l-utils gpiod
v4l2-ctl --list-devices
ls -l /dev/v4l/by-path/ /dev/v4l/by-id/
v4l2-ctl --device=/dev/video0 --all  # replace with each candidate; look for Video Capture
```

Set `ENTRY_CAMERA_DEVICE_PATH` and `EXIT_CAMERA_DEVICE_PATH` in `.env` to **different capture nodes**. Use `/dev/v4l/by-path/...` to keep ENTRY and EXIT tied to physical USB ports, or `/dev/v4l/by-id/...` if the cameras have unique serial numbers and may move between ports. A webcam can expose extra metadata nodes, and `/dev/video*` numbering can change after reboot. Compose maps the chosen host nodes to `/dev/video0` (ENTRY) and `/dev/video2` (EXIT) inside the container. Registration uses ENTRY.

To run this checkout (including local changes):

```bash
cp .env.example .env
# Edit the two camera paths in .env before starting.
docker compose build palmgate-api-usb palmgate-frontend-usb
docker compose pull palmgate-proxy-usb
docker compose up -d --no-build --pull never
```

Open `http://<device-ip>:8080`. Keep `model.tflite` and `hand_landmarker.task` in the project root. Both are mounted read-only; SQLite data persists in the `palmgate-db` volume. Run one API process so both cameras share one recognition model instance.

To use published GHCR images after these changes have been published:

```bash
cp .env.example .env
docker compose pull
docker compose up -d
```

To update the Orange Pi after pushing new code:

```bash
git pull
docker compose pull
docker compose up -d
```

The running build SHA is shown in the dashboard status card and in `/api/status` as `app.version` (local builds default to `local`).

GPIO is optional. On Orange Pi Zero 3, PC11 is **physical header pin 12**, listed as GPIO 75 in the [board manual](https://orangepi.net/wp-content/uploads/2023/12/OrangePi_Zero3_H618_user-manual_v1.1.pdf). Check the running OS before enabling the relay:

```bash
gpioinfo /dev/gpiochip0 | grep -E 'PC11|line[[:space:]]+75:'
```

The Python GPIO binding uses the kernel's [GPIO v2 interface](https://docs.kernel.org/userspace-api/gpio/chardev.html), available since Linux 5.10; check the board with `uname -r` if GPIO access fails.

Set `LOCK_GPIO_CHIP=/dev/gpiochip0` and `LOCK_GPIO_LINE=75` in `.env` if the `gpioinfo` output matches. These are the chip path and line offset, not the physical header pin number. Set `LOCK_ACTIVE_LOW=1` for a relay triggered by a low signal (`0` for high), and `LOCK_UNLOCK_MS` for its pulse duration. PC11 is a 3.3 V GPIO signal; use a 3.3 V compatible relay driver and common ground, not the pin to power a lock. Leave `LOCK_GPIO_ENABLED=0` in `.env`; the GPIO overlay enables it and maps the chip:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpio.yml up -d --no-build --pull never
```

Check both camera states with `curl http://localhost:8080/api/status` (`devices.ENTRY` and `devices.EXIT`) and inspect startup errors with `docker compose logs palmgate-api-usb`. An ALLOWED result from either camera pulses the same configured relay.

Cloudflare is optional too. Set `CLOUDFLARE_TUNNEL_TOKEN`, then enable the `tunnel-usb` profile alongside `usb` when remote access is needed.

## Current features

- **Scan Palm** — browser-camera recognition with ALLOWED / DENIED result
- **Register** — camera or upload registration that captures 5 left-hand and 5 right-hand samples and stores per-hand templates
- **Access Log** — timestamped history with ENTRY/EXIT direction, identity, ALLOWED/DENIED decision, and similarity; Excel exports include direction
- **Device Status** — shows worker state, camera state, FPS, registration state, and last recognition
- **USB Runtime** — two always-on workers with independent hold/cooldown timers and labeled previews

## Where to see recognition status

### 1. Admin dashboard
Use the **Access Log** tab to see:
- timestamp
- direction: `ENTRY` / `EXIT` (`Unspecified` for older logs and browser/upload tests)
- matched name
- `ALLOWED` / `DENIED`
- similarity score

### 2. Running shell / service logs
Recognition events are also printed to the running shell from the shared recognition path.
Examples:

```text
ALLOWED | user=Naufal | similarity=0.9100 | direction=ENTRY
DENIED | user=Unknown | similarity=0.4200 | direction=EXIT
```

For the supported Docker Compose deployment, inspect backend logs with:

```bash
docker compose logs -f palmgate-api-usb
```

## `/api/status`

The app exposes runtime status at:

```text
/api/status
```

`devices.ENTRY` and `devices.EXIT` report each camera separately. `device` remains an alias for ENTRY. Previews and scan events accept `?direction=ENTRY` or `?direction=EXIT` on `/api/device-registration/preview.mjpg`, `/preview.jpg`, and `/scan-events`. Registration endpoints always use ENTRY.

Abbreviated USB response (other fields omitted):

```json
{
  "app": {"camera_source": "usb", "device_runtime_enabled": true},
  "devices": {
    "ENTRY": {"worker_state": "running", "camera_connected": 1},
    "EXIT": {"worker_state": "running", "camera_connected": 1}
  }
}
```

## Official USB registration workflow

Production registration uses the Orange Pi USB camera, not the browser camera. The app captures 5 left-hand and 5 right-hand samples and stores one template per hand.

Sample sequence for each hand:
1. Center palm
2. Move closer
3. Move farther
4. Rotate left
5. Rotate right

Browser registration is kept only for local testing and may be less reliable on the USB device.

## Seed initial users from photos

You can bootstrap temporary users from named full-hand images in `seeds/`:

```bash
python scripts/seed_users.py seeds
```

Each image or folder label must use `nim_name` format, for example `12345_Naufal.jpg`. For the local `Dataset_Webcam/` test-only folders that do not include NIMs, use:

```bash
python scripts/seed_users.py Dataset_Webcam --replace-users --auto-demo-nim
```

This generates stable demo NIMs such as `SEED-001`; do not use that flag for production enrollment.

The script uses the same MediaPipe embedding path as runtime and stores a template for test seeding. Existing users are skipped by default and access logs are preserved. To replace registered users while keeping logs:

```bash
python scripts/seed_users.py seeds --replace-users
```

Seeded users are for initial testing only. Re-register users with the USB two-hand flow before using the system for a real door lock.

## Orange Pi workflow

### Phase 1 — iPhone test mode over Wi-Fi
This is the easiest way to test before attaching a USB camera.

1. Run the API on the Orange Pi:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
2. Put the Orange Pi and iPhone on the same Wi-Fi network
3. Open `http://<orange-pi-ip>:8000` on the iPhone
4. Use the phone camera for:
   - **Scan** tab testing
   - **Register** tab enrollment
5. Use **Log** and the new status card to monitor results

### Phase 2 — USB camera mode
When both USB cameras are connected to the Orange Pi, run both device workers:

```bash
DEVICE_RUNTIME_ENABLED=1 CAMERA_SOURCE=usb ENTRY_CAMERA_DEVICE_PATH=/dev/video0 EXIT_CAMERA_DEVICE_PATH=/dev/video2 python -m app.device_runtime
```

The worker will:
- capture frames from the ENTRY and EXIT USB cameras
- wait for the palm hold threshold
- run recognition
- commit recognition attempts with the capturing camera's direction to the same SQLite database before publishing a result or unlocking
- update `/api/status`

## Orange Pi service management

This repository does not include systemd unit files. Use the USB Docker Compose profile for the always-on API, frontend, device worker, and proxy:

```bash
cp .env.example .env
docker compose pull
docker compose --profile usb up -d
```

Manage the deployment with Compose:

```bash
docker compose ps
docker compose restart
docker compose logs -f palmgate-api-usb
```

## How recognition works

1. Frames use MediaPipe hand landmarks to crop the palm ROI.
2. The ROI is converted to grayscale, blurred with a `5×5` Gaussian kernel, enhanced with CLAHE, converted back to RGB, resized to `224×224`, and kept as `0–255` float32 input.
3. The fixed root `model.tflite` runs on rotations `0°`, `-6°`, and `+6°` and returns 128-dimensional embeddings.
4. Each embedding is L2-normalized, averaged, and normalized again.
5. Cosine similarity compares the query embedding against stored per-hand templates using `SIMILARITY_THRESHOLD`, which defaults to `0.75`.
6. Result is recorded as `ALLOWED` or `DENIED`, with ENTRY/EXIT taken from the worker's fixed camera role. Browser/upload tests have no direction. An allowed attempt indicates recognition approval, not proof that someone physically passed the door.

Adding direction migrates the database automatically and preserves existing users and logs. Existing rows keep an unspecified direction. No database reset is needed for this update. Cooldowns are independent per camera; a palm left in view can produce another attempt after the next hold/cooldown cycle.

## Cross-device / cross-brightness reliability

USB registration captures 5 samples per hand, averages each hand into a normalized template, and compares recognition queries against those templates. Combined with brightness normalization, this improves accuracy when enrollment and recognition cameras differ.

## Database migration notice

> **Historical preprocessing change** — embeddings generated before the existing preprocessing pipeline changed are **not compatible** with the current version. This is separate from the automatic ENTRY/EXIT migration above.
>
> Stop PalmGate, remove the old database, and re-register users. For a local process:
>
> ```bash
> rm palmprint.db
> ```
>
> Docker Compose stores `/data/palmprint.db` in a named volume, so a host-side `rm palmprint.db` does not reset it. To remove the Compose database:
>
> ```bash
> docker compose down -v
> ```
>
> Removing the database or Compose volume also deletes users, embeddings, access logs, and persisted device status.

## Tests

```bash
python -m pytest tests/ -v
```

To run local checks while leaving Docker checks for later:

```bash
PALMGATE_SKIP_DOTENV=1 python -m pytest tests/ --ignore=tests/test_docker_requirements.py --ignore=tests/test_docker_frontend_deployment.py
cd frontend
bun install --frozen-lockfile
bun run test
bun run build
```
