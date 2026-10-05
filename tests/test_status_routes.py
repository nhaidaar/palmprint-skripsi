from fastapi.testclient import TestClient

from app.main import app



def test_status_endpoint_returns_device_status():
    client = TestClient(app)
    response = client.get("/api/status")

    assert response.status_code == 200
    data = response.json()
    assert "app" in data
    assert "device" in data
    assert "database" in data
    assert "camera_source" in data["app"]
    assert "device_runtime_enabled" in data["app"]


def test_debug_status_reports_disabled_hardware_even_with_saved_usb_state(monkeypatch):
    import app.main as main
    import app.routes.status as status_route

    class SavedDeviceDB:
        def get_device_status(self, direction="ENTRY"):
            return {"worker_state": "running", "camera_connected": 1}

    monkeypatch.setattr(main, "db", SavedDeviceDB())
    monkeypatch.setattr(main, "device_runtime", None)
    monkeypatch.setattr(main, "exit_device_runtime", None)
    monkeypatch.setattr(status_route, "APP_DEBUG", True, raising=False)
    monkeypatch.setattr(status_route, "DEVICE_RUNTIME_ENABLED", False)
    monkeypatch.setattr(status_route, "LOCK_GPIO_ENABLED", False, raising=False)
    data = TestClient(app).get("/api/status").json()
    assert data["app"]["debug"] is True
    assert data["app"]["mode"] == "debug"
    assert data["app"]["gpio_enabled"] is False
    assert all(device["worker_state"] == "disabled" and device["camera_connected"] == 0
               for device in data["devices"].values())


def test_status_includes_usb_scan_state(monkeypatch):
    import app.main as main

    class FakeRuntime:
        worker_state = "running"
        registration_session = None
        scan_state = {"stage": "waiting_for_hand", "metrics": {"hand_detected": False}}

    monkeypatch.setattr(main, "device_runtime", FakeRuntime())
    client = TestClient(app)

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["device"]["scan_state"]["stage"] == "waiting_for_hand"


def test_status_includes_registration_runtime_state(monkeypatch):
    import app.main as main

    class FakeSession:
        id = "session-1"
        current_sample_index = 3
        captured_samples = [{}, {}, {}]

    class FakeRuntime:
        worker_state = "registration_active"
        registration_session = FakeSession()

    monkeypatch.setattr(main, "device_runtime", FakeRuntime())
    client = TestClient(app)

    response = client.get("/api/status")

    assert response.status_code == 200
    device = response.json()["device"]
    assert device["worker_state"] == "registration_active"
    assert device["registration_active"] is True
    assert device["registration_captured_count"] == 3


def test_status_includes_environment_and_dev_features(monkeypatch):
    import app.routes.status as status_route

    monkeypatch.setattr(status_route, "APP_ENV", "development")
    monkeypatch.setattr(status_route, "DEV_FEATURES_ENABLED", True)

    client = TestClient(app)
    response = client.get("/api/status")

    assert response.status_code == 200
    app_status = response.json()["app"]
    assert app_status["environment"] == "development"
    assert app_status["dev_features"] is True


def test_status_reports_configured_app_version(monkeypatch):
    import app.routes.status as status_route

    monkeypatch.setattr(status_route, "PALMGATE_VERSION", "8f5f5d1")

    client = TestClient(app)
    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["app"]["version"] == "8f5f5d1"
