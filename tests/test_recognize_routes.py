import asyncio
import base64
import logging

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app


def encoded_image():
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    ok, data = cv2.imencode(".jpg", frame)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(data.tobytes()).decode("ascii")


def test_encode_roi_image_logs_warning_when_imencode_fails(monkeypatch, caplog):
    import app.routes.recognize as recognize_route

    monkeypatch.setattr(recognize_route.cv2, "imencode", lambda *args, **kwargs: (False, None))

    with caplog.at_level(logging.WARNING, logger="palmgate"):
        roi_image = recognize_route.encode_roi_image(np.zeros((2, 2, 3), dtype=np.uint8))

    assert roi_image is None
    assert "ROI preview encoding failed" in caplog.text


def test_save_debug_images_runs_disk_writes_in_thread(monkeypatch, tmp_path):
    import app.routes.recognize as recognize_route

    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(recognize_route, "RECOGNITION_DEBUG_DIR", tmp_path)
    monkeypatch.setattr(recognize_route.asyncio, "to_thread", fake_to_thread)

    paths = asyncio.run(recognize_route.save_debug_images(
        np.zeros((20, 30, 3), dtype=np.uint8),
        np.full((224, 224, 3), 128, dtype=np.uint8),
        "camera",
    ))

    assert calls == ["_write_debug_images"]
    assert paths["frame"].endswith("_camera_frame.jpg")
    assert paths["roi"].endswith("_camera_roi.jpg")


def test_recognize_full_frame_uses_processed_roi_embedding(monkeypatch):
    import app.main as main

    class FakeProcessor:
        def __init__(self):
            self.used_processed_roi = False

        def extract_embedding_from_frame(self, frame):
            self.used_processed_roi = True
            return np.ones(4, dtype=np.float32), np.zeros((2, 2, 3), dtype=np.uint8)

        def compute_similarity(self, embedding, stored, threshold):
            return {
                "status": "DENIED",
                "name": "Unknown",
                "similarity": 0.1,
                "closest_match": None,
                "user_id": None,
            }

    class FakeDB:
        def get_all_embeddings(self):
            return []

        def add_access_log(self, user_id, matched_name, status, similarity, duration_ms=None, description=None):
            pass

    processor = FakeProcessor()
    monkeypatch.setattr(main, "palm_processor", processor)
    monkeypatch.setattr(main, "db", FakeDB())
    client = TestClient(app)

    response = client.post("/api/recognize", json={"image": encoded_image(), "is_roi": False})

    assert response.status_code == 200
    assert processor.used_processed_roi is True


def test_recognize_roi_accepts_but_does_not_forward_rotation_angle(monkeypatch):
    import app.main as main
    import app.routes.recognize as recognize_route

    class FakeProcessor:
        def __init__(self):
            self.calls = 0

        def extract_embedding_from_roi(self, roi):
            self.calls += 1
            return np.ones(4, dtype=np.float32), np.zeros((2, 2, 3), dtype=np.uint8)

        def compute_similarity(self, embedding, stored, threshold):
            return {
                "status": "DENIED",
                "name": "Unknown",
                "similarity": 0.1,
                "closest_match": None,
                "user_id": None,
            }

    class FakeDB:
        def get_all_embeddings(self):
            return []

        def add_access_log(self, *args, **kwargs):
            pass

    processor = FakeProcessor()
    monkeypatch.setattr(main, "palm_processor", processor)
    monkeypatch.setattr(main, "db", FakeDB())
    monkeypatch.setattr(
        recognize_route,
        "decode_base64_image",
        lambda image: np.zeros((2, 2, 3), dtype=np.uint8),
    )
    client = TestClient(app)

    response = client.post(
        "/api/recognize",
        json={"image": "img", "is_roi": True, "rotation_angle": 30.0},
    )

    assert response.status_code == 200
    assert processor.calls == 1


def test_recognize_returns_roi_image_in_dev_debug_mode(monkeypatch, tmp_path):
    import app.main as main
    import app.routes.recognize as recognize_route

    class FakeProcessor:
        def extract_embedding_from_frame(self, frame):
            self.used_debug_roi = True
            return np.ones(4, dtype=np.float32), np.full((224, 224, 3), 128, dtype=np.uint8)

        def compute_similarity(self, embedding, stored, threshold):
            return {
                "status": "ALLOWED",
                "name": "Alice",
                "similarity": 0.75,
                "closest_match": "Alice",
                "user_id": 1,
            }

    class FakeDB:
        def get_all_embeddings(self):
            return [{"id": 1, "name": "Alice", "embedding": np.ones(4, dtype=np.float32)}]

        def add_access_log(self, *args, **kwargs):
            pass

    fake_processor = FakeProcessor()
    monkeypatch.setattr(main, "palm_processor", fake_processor)
    monkeypatch.setattr(main, "db", FakeDB())
    monkeypatch.setattr(recognize_route, "DEV_FEATURES_ENABLED", True)
    monkeypatch.setattr(recognize_route, "RECOGNITION_DEBUG_DIR", tmp_path)
    monkeypatch.setattr(recognize_route, "decode_base64_image", lambda image: np.zeros((20, 20, 3), dtype=np.uint8))

    client = TestClient(app)
    response = client.post("/api/recognize", json={"image": "img", "debug_roi": True})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ALLOWED"
    assert data["roi_image"].startswith("data:image/jpeg;base64,")
    assert fake_processor.used_debug_roi is True


def test_recognize_saves_debug_frame_and_roi_in_dev_debug_mode(monkeypatch, tmp_path):
    import app.main as main
    import app.routes.recognize as recognize_route

    class FakeProcessor:
        def extract_embedding_from_frame(self, frame):
            return np.ones(4, dtype=np.float32), np.full((224, 224, 3), 128, dtype=np.uint8)

        def compute_similarity(self, embedding, stored, threshold):
            return {"status": "DENIED", "name": "Unknown", "similarity": 0.1, "closest_match": None, "user_id": None}

    class FakeDB:
        def get_all_embeddings(self):
            return []

        def add_access_log(self, *args, **kwargs):
            pass

    monkeypatch.setattr(main, "palm_processor", FakeProcessor())
    monkeypatch.setattr(main, "db", FakeDB())
    monkeypatch.setattr(recognize_route, "DEV_FEATURES_ENABLED", True)
    monkeypatch.setattr(recognize_route, "RECOGNITION_DEBUG_DIR", tmp_path)
    monkeypatch.setattr(recognize_route, "decode_base64_image", lambda image: np.zeros((20, 30, 3), dtype=np.uint8))

    client = TestClient(app)
    response = client.post("/api/recognize", json={"image": "img", "debug_roi": True, "source": "camera"})

    assert response.status_code == 200
    paths = response.json()["debug_image_paths"]
    assert paths["frame"].endswith("_camera_frame.jpg")
    assert paths["roi"].endswith("_camera_roi.jpg")
    assert cv2.imread(paths["frame"]).shape[:2] == (20, 30)
    assert cv2.imread(paths["roi"]).shape[:2] == (224, 224)


def test_recognize_discards_processed_roi_when_debug_roi_is_disabled(monkeypatch):
    import app.main as main
    import app.routes.recognize as recognize_route

    class FakeProcessor:
        def extract_embedding_from_frame(self, frame):
            return np.ones(4, dtype=np.float32), np.full((224, 224, 3), 128, dtype=np.uint8)

        def compute_similarity(self, embedding, stored, threshold):
            return {"status": "DENIED", "name": "Unknown", "similarity": 0.1, "closest_match": None, "user_id": None}

    class FakeDB:
        def get_all_embeddings(self):
            return []

        def add_access_log(self, *args, **kwargs):
            pass

    fake_processor = FakeProcessor()
    monkeypatch.setattr(main, "palm_processor", fake_processor)
    monkeypatch.setattr(main, "db", FakeDB())
    monkeypatch.setattr(recognize_route, "DEV_FEATURES_ENABLED", True)
    monkeypatch.setattr(recognize_route, "decode_base64_image", lambda image: np.zeros((20, 20, 3), dtype=np.uint8))

    client = TestClient(app)
    response = client.post("/api/recognize", json={"image": "img", "debug_roi": False})

    assert response.status_code == 200
    assert "roi_image" not in response.json()


def test_recognize_does_not_return_roi_image_in_production(monkeypatch):
    import app.main as main
    import app.routes.recognize as recognize_route

    class FakeProcessor:
        def extract_embedding_from_frame(self, frame):
            return np.ones(4, dtype=np.float32), np.zeros((2, 2, 3), dtype=np.uint8)

        def compute_similarity(self, embedding, stored, threshold):
            return {"status": "DENIED", "name": "Unknown", "similarity": 0.1, "closest_match": None, "user_id": None}

    class FakeDB:
        def get_all_embeddings(self):
            return []

        def add_access_log(self, *args, **kwargs):
            pass

    monkeypatch.setattr(main, "palm_processor", FakeProcessor())
    monkeypatch.setattr(main, "db", FakeDB())
    monkeypatch.setattr(recognize_route, "DEV_FEATURES_ENABLED", False)
    monkeypatch.setattr(recognize_route, "decode_base64_image", lambda image: np.zeros((20, 20, 3), dtype=np.uint8))

    client = TestClient(app)
    response = client.post("/api/recognize", json={"image": "img", "debug_roi": True})

    assert response.status_code == 200
    data = response.json()
    assert data["closest_match"] is None
    assert "roi_image" not in data
