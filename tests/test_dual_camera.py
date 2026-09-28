from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import sqlite3

import numpy as np
from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest

from app.database import Database


def test_directional_logs_survive_concurrent_writes_and_reopen(tmp_path, monkeypatch):
    import app.main as main

    path = tmp_path / "access.db"
    db = Database(path)
    user_id = db.add_user("Alice", np.ones(128), nim="A001")

    def capture(direction):
        for _ in range(30):
            db.add_access_log(user_id, "Alice", "ALLOWED", 0.95, direction=direction)
            db.add_access_log(None, "Unknown", "DENIED", 0.2, direction=direction)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(capture, ("ENTRY", "EXIT")))
    db.close()
    db = Database(path)
    monkeypatch.setattr(main, "db", db)
    try:
        client = TestClient(main.app)
        rows = client.get("/api/logs?limit=200").json()
        assert len(rows) == 120
        for direction in ("ENTRY", "EXIT"):
            for status in ("ALLOWED", "DENIED"):
                assert sum(row["direction"] == direction and row["status"] == status for row in rows) == 30
        assert all(row["timestamp"] for row in rows)
        assert client.get("/api/logs/count").json() == {"count": 120}
    finally:
        db.close()


def test_existing_database_preserves_history_and_separates_camera_status(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE access_logs (
                id INTEGER PRIMARY KEY, user_id INTEGER, matched_name TEXT,
                status TEXT, similarity REAL, timestamp TEXT
            );
            INSERT INTO access_logs VALUES (1, NULL, 'Unknown', 'DENIED', 0.2, '2026-07-01 10:00:00');
            CREATE TABLE device_status (
                id INTEGER PRIMARY KEY CHECK (id = 1), worker_state TEXT,
                camera_connected INTEGER, last_error TEXT, fps REAL,
                last_inference_ms REAL, last_recognition_at TEXT, updated_at TEXT
            );
            INSERT INTO device_status VALUES (1, 'running', 1, NULL, 4, 20, NULL, '2026-07-01 10:00:00');
        """)
    db = Database(path)
    try:
        assert db.get_access_logs()[0]["direction"] is None
        assert db.get_access_logs()[0]["timestamp"] == "2026-07-01 10:00:00"
        db.upsert_device_status(direction="EXIT", worker_state="error", camera_connected=False,
                                last_error="unplugged", fps=None, last_inference_ms=None)
        assert db.get_device_status("ENTRY")["worker_state"] == "running"
        assert db.get_device_status("EXIT")["last_error"] == "unplugged"
        with pytest.raises(ValueError, match="direction"):
            db.add_access_log(None, "Unknown", "DENIED", 0.2, direction="INVALID")
        assert db.count_access_logs() == 1
    finally:
        db.close()


@pytest.mark.parametrize(("enrolled", "status", "name"), [(True, "ALLOWED", "Alice"), (False, "DENIED", "Unknown")])
def test_workers_log_their_own_direction_with_independent_cooldowns(tmp_path, enrolled, status, name):
    from app.device_runtime import DeviceRuntime
    from app.palm_processor import PalmProcessor

    class Clock:
        now_ms = 0

        def now(self):
            return self.now_ms

    class Camera:
        disconnected = False

        def read(self):
            if self.disconnected:
                raise RuntimeError("camera disconnected")
            return np.full((10, 10, 3), 128, dtype=np.uint8)

    class Processor(PalmProcessor):
        def __init__(self):
            pass  # Substitute image inference; matching and persistence stay real.

        def get_registration_guidance_metrics(self, frame, previous_metrics=None):
            return {"hand_detected": True}

        def extract_embedding_from_frame(self, frame):
            return np.ones(128, dtype=np.float32), None

    class Lock:
        unlocks = 0

        def unlock(self):
            self.unlocks += 1

    db = Database(tmp_path / "workers.db")
    if enrolled:
        db.add_user("Alice", np.ones(128), nim="A001")
    processor = Processor()
    clock = Clock()
    lock = Lock()
    try:
        entry, exit = [
            DeviceRuntime(Camera(), processor, db, clock=clock, hold_ms=1000,
                          direction=direction, lock_controller=lock)
            for direction in ("ENTRY", "EXIT")
        ]
        entry.tick()
        clock.now_ms = 1000
        assert entry.tick()["direction"] == "ENTRY"
        exit.tick()
        clock.now_ms = 2000
        assert entry.tick() is None
        assert exit.tick()["direction"] == "EXIT"
        assert [(row["direction"], row["matched_name"], row["status"]) for row in db.get_access_logs()] == [
            ("EXIT", name, status), ("ENTRY", name, status)
        ]
        entry.camera.disconnected = True
        with pytest.raises(RuntimeError, match="disconnected"):
            entry.capture_preview_frame()
        assert entry.get_latest_frame_jpeg() is None
        clock.now_ms = 5000
        with pytest.raises(RuntimeError, match="disconnected"):
            entry.tick()
        assert db.count_access_logs() == 2
        assert lock.unlocks == (2 if enrolled else 0)
        # A failed insert must neither emit a successful scan nor unlock the door.
        entry.camera.disconnected = False
        events = entry.scan_broadcaster.subscribe()
        db.conn.execute("""
            CREATE TRIGGER reject_log BEFORE INSERT ON access_logs
            BEGIN SELECT RAISE(ABORT, 'log write failed'); END
        """)
        entry.tick()
        clock.now_ms = 6000
        with pytest.raises(sqlite3.IntegrityError, match="log write failed"):
            entry.tick()
        assert events.empty()
        assert lock.unlocks == (2 if enrolled else 0)
        assert db.count_access_logs() == 2
    finally:
        db.close()


def test_app_starts_two_cameras_shares_processor_and_routes_previews(tmp_path, monkeypatch):
    import app.main as main
    import app.device_runtime as runtime_module

    cameras = []
    processors = []

    class Camera:
        closed = False

        def __init__(self, path):
            self.path = path
            cameras.append(self)

        def read(self):
            return np.full((10, 10, 3), 30 if self.path == "entry" else 200, dtype=np.uint8)

        def close(self):
            self.closed = True

    class Processor:
        closed = False

        def __init__(self):
            processors.append(self)

        def get_registration_guidance_metrics(self, frame, previous_metrics=None):
            return {"hand_detected": False}

        def close(self):
            self.closed = True

    monkeypatch.setattr(main, "PalmProcessor", Processor)
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "startup.db")
    monkeypatch.setattr(main, "DEVICE_RUNTIME_ENABLED", True)
    monkeypatch.setattr(main, "CAMERA_SOURCE", "usb")
    monkeypatch.setattr(runtime_module, "ENTRY_CAMERA_DEVICE_PATH", "entry", raising=False)
    monkeypatch.setattr(runtime_module, "EXIT_CAMERA_DEVICE_PATH", "exit", raising=False)
    monkeypatch.setattr(runtime_module, "OpenCVCameraSource", Camera)
    with TestClient(main.app) as client:
        assert [camera.path for camera in cameras] == ["entry", "exit"]
        assert len(processors) == 1
        assert main.device_runtime.palm_processor is main.exit_device_runtime.palm_processor
        assert main.device_runtime.lock_controller is main.exit_device_runtime.lock_controller
        for runtime in (main.device_runtime, main.exit_device_runtime):
            runtime.capture_preview_frame()
            runtime.tick()
        status = client.get("/api/status").json()
        assert set(status["devices"]) == {"ENTRY", "EXIT"}
        entry = client.get("/api/device-registration/preview.jpg?direction=ENTRY")
        exit = client.get("/api/device-registration/preview.jpg?direction=EXIT")
        assert entry.status_code == exit.status_code == 200
        assert entry.content != exit.content
        assert client.get("/api/device-registration/preview.jpg?direction=OTHER").status_code == 422
        assert client.post("/api/device-registration/start", json={"nim": "A1", "name": "Alice"}).status_code == 200
        assert main.device_runtime.registration_session is not None
        assert main.exit_device_runtime.registration_session is None
    assert all(camera.closed for camera in cameras)
    assert processors[0].closed


def test_excel_export_includes_capture_direction(tmp_path, monkeypatch):
    import app.main as main

    db = Database(tmp_path / "export.db")
    monkeypatch.setattr(main, "db", db)
    try:
        db.add_access_log(None, "Unknown", "DENIED", 0.2, direction="EXIT")
        response = TestClient(main.app).get("/api/logs/export.xlsx")
        sheet = load_workbook(BytesIO(response.content))["Access Logs"]
        assert sheet["H4"].value == "Direction"
        assert sheet["H5"].value == "EXIT"
        assert sheet.auto_filter.ref == "A4:H5"
    finally:
        db.close()


def test_same_camera_cannot_be_assigned_to_both_directions(tmp_path, monkeypatch):
    import app.device_runtime as runtime_module

    camera = tmp_path / "camera"
    camera.touch()
    alias = tmp_path / "alias"
    alias.symlink_to(camera)
    monkeypatch.setattr(runtime_module, "ENTRY_CAMERA_DEVICE_PATH", str(camera))
    monkeypatch.setattr(runtime_module, "EXIT_CAMERA_DEVICE_PATH", str(alias))
    with pytest.raises(ValueError, match="different camera devices"):
        runtime_module.build_device_runtime(None, None)
