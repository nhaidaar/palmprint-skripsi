import numpy as np
from fastapi.testclient import TestClient

from app.main import app


class FakeDB:
    def __init__(self):
        self.individual_embeddings = None
        self.embedding_hands = None

    def get_all_embeddings(self):
        return []

    def add_user(self, name, embedding, *, nim, individual_embeddings=None, embedding_hands=None):
        self.nim = nim
        self.name = name
        self.embedding = embedding
        self.individual_embeddings = individual_embeddings
        self.embedding_hands = embedding_hands
        return 123


class FakeProcessor:
    def __init__(self, duplicate=False):
        self.next_value = 0
        self.duplicate = duplicate
        self.similarity_checks = 0
        self.frames_seen = []
        self.rois_seen = []

    def _next_embedding(self):
        self.next_value += 1
        return np.full(4, self.next_value, dtype=np.float32), None

    def extract_embedding_from_roi(self, roi):
        self.rois_seen.append(roi)
        return self._next_embedding()

    def extract_embedding_from_frame(self, frame):
        self.frames_seen.append(frame)
        return self._next_embedding()

    def compute_similarity(self, embedding, stored, threshold):
        self.similarity_checks += 1
        if self.duplicate:
            return {"status": "ALLOWED", "name": "Existing", "similarity": 0.9}
        return {"status": "DENIED", "name": "Unknown", "similarity": 0.1}


def test_register_rejects_images_without_hand_selection():
    client = TestClient(app)

    response = client.post("/api/register", json={"nim": "12345", "name": "Alice", "images": ["img"] * 9})

    assert response.status_code == 400
    assert "Select at least one hand" in response.json()["detail"]


def test_register_rejects_missing_hand_labels():
    client = TestClient(app)

    response = client.post("/api/register", json={"nim": "12345", "name": "Alice", "images": ["img"] * 10})

    assert response.status_code == 400
    assert "Select at least one hand" in response.json()["detail"]


def test_register_rejects_unbalanced_hand_labels():
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={"nim": "12345", "name": "Alice", "images": ["img"] * 10, "hands": ["left"] * 10},
    )

    assert response.status_code == 400
    assert "5 images for each selected hand" in response.json()["detail"]


def test_register_saves_five_embeddings_per_selected_hand_with_nim(monkeypatch):
    import app.main as main
    import app.routes.register as register_route

    fake_db = FakeDB()
    fake_processor = FakeProcessor()
    monkeypatch.setattr(main, "db", fake_db)
    monkeypatch.setattr(main, "palm_processor", fake_processor)
    monkeypatch.setattr(register_route, "decode_base64_image", lambda image: np.zeros((2, 2, 3), dtype=np.uint8))
    client = TestClient(app)

    hands = ["left"] * 5 + ["right"] * 5
    response = client.post(
        "/api/register",
        json={"nim": "12345", "name": "Alice", "images": ["img"] * 10, "hands": hands, "is_roi": True},
    )

    assert response.status_code == 200
    assert fake_db.nim == "12345"
    assert len(fake_db.individual_embeddings) == 10
    assert fake_db.embedding_hands == ["left"] * 5 + ["right"] * 5
    assert [float(emb[0]) for emb in fake_db.individual_embeddings] == list(range(1, 11))
    assert len(fake_processor.rois_seen) == 10
    assert fake_processor.frames_seen == []
    assert fake_processor.similarity_checks == 2


def test_register_full_frames_do_not_forward_rotation_angle(monkeypatch):
    import app.main as main
    import app.routes.register as register_route

    fake_db = FakeDB()
    fake_processor = FakeProcessor()
    decoded_frame = np.zeros((2, 2, 3), dtype=np.uint8)
    monkeypatch.setattr(main, "db", fake_db)
    monkeypatch.setattr(main, "palm_processor", fake_processor)
    monkeypatch.setattr(register_route, "decode_base64_image", lambda image: decoded_frame)
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={
            "nim": "12345",
            "name": "Alice",
            "images": ["img"] * 5,
            "hands": ["left"] * 5,
            "is_roi": False,
            "rotation_angle": 30.0,
        },
    )

    assert response.status_code == 200
    assert len(fake_processor.frames_seen) == 5
    assert fake_processor.rois_seen == []
    assert all(frame is decoded_frame for frame in fake_processor.frames_seen)
    assert [float(embedding[0]) for embedding in fake_db.individual_embeddings] == [1, 2, 3, 4, 5]


def test_register_rejects_duplicate_candidate_embedding(monkeypatch):
    import app.main as main
    import app.routes.register as register_route

    monkeypatch.setattr(main, "db", FakeDB())
    monkeypatch.setattr(main, "palm_processor", FakeProcessor(duplicate=True))
    monkeypatch.setattr(register_route, "decode_base64_image", lambda image: np.zeros((2, 2, 3), dtype=np.uint8))
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={
            "nim": "12345",
            "name": "Alice",
            "images": ["img"] * 10,
            "hands": ["left"] * 5 + ["right"] * 5,
            "is_roi": True,
        },
    )

    assert response.status_code == 409
    assert "already registered" in response.json()["detail"]


def test_register_rejects_missing_nim():
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={"name": "Alice", "images": ["img"] * 10, "hands": ["left"] * 5 + ["right"] * 5},
    )

    assert response.status_code == 400
    assert "NIM is required" in response.json()["detail"]


def test_register_rejects_duplicate_nim(monkeypatch):
    import app.main as main
    import app.routes.register as register_route

    class DuplicateNimDB(FakeDB):
        def add_user(self, name, embedding, *, nim, individual_embeddings=None, embedding_hands=None):
            raise ValueError("NIM already exists")

    monkeypatch.setattr(main, "db", DuplicateNimDB())
    monkeypatch.setattr(main, "palm_processor", FakeProcessor())
    monkeypatch.setattr(register_route, "decode_base64_image", lambda image: np.zeros((2, 2, 3), dtype=np.uint8))
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={
            "nim": "12345",
            "name": "Alice",
            "images": ["img"] * 10,
            "hands": ["left"] * 5 + ["right"] * 5,
            "is_roi": True,
        },
    )

    assert response.status_code == 409
    assert "NIM already exists" in response.json()["detail"]


def test_register_saves_left_only_embeddings(monkeypatch):
    import app.main as main
    import app.routes.register as register_route

    fake_db = FakeDB()
    fake_processor = FakeProcessor()
    monkeypatch.setattr(main, "db", fake_db)
    monkeypatch.setattr(main, "palm_processor", fake_processor)
    monkeypatch.setattr(register_route, "decode_base64_image", lambda image: np.zeros((2, 2, 3), dtype=np.uint8))
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={"nim": "12345", "name": "Alice", "images": ["img"] * 5, "hands": ["left"] * 5, "is_roi": True},
    )

    assert response.status_code == 200
    assert len(fake_db.individual_embeddings) == 5
    assert fake_db.embedding_hands == ["left"] * 5
    assert [float(emb[0]) for emb in fake_db.individual_embeddings] == [1, 2, 3, 4, 5]
    assert fake_processor.similarity_checks == 1


def test_register_saves_right_only_embeddings(monkeypatch):
    import app.main as main
    import app.routes.register as register_route

    fake_db = FakeDB()
    fake_processor = FakeProcessor()
    monkeypatch.setattr(main, "db", fake_db)
    monkeypatch.setattr(main, "palm_processor", fake_processor)
    monkeypatch.setattr(register_route, "decode_base64_image", lambda image: np.zeros((2, 2, 3), dtype=np.uint8))
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={"nim": "12345", "name": "Alice", "images": ["img"] * 5, "hands": ["right"] * 5, "is_roi": True},
    )

    assert response.status_code == 200
    assert len(fake_db.individual_embeddings) == 5
    assert fake_db.embedding_hands == ["right"] * 5
    assert [float(emb[0]) for emb in fake_db.individual_embeddings] == [1, 2, 3, 4, 5]
    assert fake_processor.similarity_checks == 1


def test_register_rejects_missing_selected_hand_samples():
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={"nim": "12345", "name": "Alice", "images": ["img"] * 4, "hands": ["left"] * 4},
    )

    assert response.status_code == 400
    assert "5 images for each selected hand" in response.json()["detail"]


def test_register_rejects_upload_source_in_production(monkeypatch):
    import app.routes.register as register_route

    monkeypatch.setattr(register_route, "DEV_FEATURES_ENABLED", False)
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={
            "nim": "12345",
            "name": "Alice",
            "images": ["img"] * 5,
            "hands": ["left"] * 5,
            "source": "upload",
        },
    )

    assert response.status_code == 403
    assert "development mode" in response.json()["detail"]


def test_register_rejects_unknown_source(monkeypatch):
    import app.routes.register as register_route

    monkeypatch.setattr(register_route, "DEV_FEATURES_ENABLED", True)
    client = TestClient(app)

    response = client.post(
        "/api/register",
        json={
            "nim": "12345",
            "name": "Alice",
            "images": ["img"] * 5,
            "hands": ["left"] * 5,
            "source": "kiosk",
        },
    )

    assert response.status_code == 400
    assert "Invalid registration source" in response.json()["detail"]
