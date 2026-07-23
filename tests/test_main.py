import asyncio

import pytest

import app.main as main


class FakeDatabase:
    instances = []

    def __init__(self, path):
        self.path = path
        self.closed = False
        self.__class__.instances.append(self)

    def close(self):
        self.closed = True


class FakePalmProcessor:
    instances = []

    def __init__(self):
        self.closed = False
        self.__class__.instances.append(self)

    def close(self):
        self.closed = True


def reset_runtime_globals():
    main.db = None
    main.palm_processor = None
    main.device_runtime = None


def test_lifespan_constructs_processor_without_model_argument_and_cleans_up(monkeypatch):
    FakeDatabase.instances.clear()
    FakePalmProcessor.instances.clear()
    reset_runtime_globals()
    monkeypatch.setattr(main, "Database", FakeDatabase)
    monkeypatch.setattr(main, "PalmProcessor", FakePalmProcessor)
    monkeypatch.setattr(main, "DEVICE_RUNTIME_ENABLED", False)
    monkeypatch.setattr(main, "CAMERA_SOURCE", "browser")

    async def run_lifespan():
        async with main.lifespan(main.app):
            assert main.db is FakeDatabase.instances[0]
            assert main.palm_processor is FakePalmProcessor.instances[0]

    asyncio.run(run_lifespan())

    assert FakeDatabase.instances[0].closed is True
    assert FakePalmProcessor.instances[0].closed is True
    assert main.db is None
    assert main.palm_processor is None


def test_lifespan_closes_database_when_model_startup_fails(monkeypatch):
    FakeDatabase.instances.clear()
    reset_runtime_globals()
    sentinel = RuntimeError("model failed")

    class BrokenPalmProcessor:
        def __init__(self):
            raise sentinel

    monkeypatch.setattr(main, "Database", FakeDatabase)
    monkeypatch.setattr(main, "PalmProcessor", BrokenPalmProcessor)
    monkeypatch.setattr(main, "DEVICE_RUNTIME_ENABLED", False)
    monkeypatch.setattr(main, "CAMERA_SOURCE", "browser")

    async def run_lifespan():
        async with main.lifespan(main.app):
            raise AssertionError("lifespan must not yield")

    with pytest.raises(RuntimeError, match="model failed") as exc_info:
        asyncio.run(run_lifespan())

    assert exc_info.value is sentinel
    assert FakeDatabase.instances[0].closed is True
    assert main.db is None
    assert main.palm_processor is None


def test_lifespan_preserves_body_error_and_cleans_up_when_device_stop_fails(monkeypatch):
    FakeDatabase.instances.clear()
    FakePalmProcessor.instances.clear()
    reset_runtime_globals()
    body_error = RuntimeError("body failed")
    stop_error = asyncio.CancelledError("stop cancelled")

    class FailingDeviceRuntime:
        def __init__(self):
            self.started = False
            self.stop_called = False

        def start(self):
            self.started = True

        def stop(self):
            self.stop_called = True
            raise stop_error

    runtime = FailingDeviceRuntime()
    monkeypatch.setattr(main, "Database", FakeDatabase)
    monkeypatch.setattr(main, "PalmProcessor", FakePalmProcessor)
    monkeypatch.setattr(main, "build_device_runtime", lambda processor, db: runtime)
    monkeypatch.setattr(main, "DEVICE_RUNTIME_ENABLED", True)
    monkeypatch.setattr(main, "CAMERA_SOURCE", "usb")

    async def run_lifespan():
        async with main.lifespan(main.app):
            assert runtime.started is True
            raise body_error

    with pytest.raises(RuntimeError, match="body failed") as exc_info:
        asyncio.run(run_lifespan())

    assert exc_info.value is body_error
    assert runtime.stop_called is True
    assert FakePalmProcessor.instances[0].closed is True
    assert FakeDatabase.instances[0].closed is True
    assert main.device_runtime is None
    assert main.palm_processor is None
    assert main.db is None
