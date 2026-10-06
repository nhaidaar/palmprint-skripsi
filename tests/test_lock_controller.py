import pytest


def test_debug_never_initializes_gpio_even_when_requested(monkeypatch):
    import sys
    import app.config as config
    from app.lock_controller import NoopLockController, build_lock_controller

    monkeypatch.setattr(config, "APP_DEBUG", True)
    monkeypatch.setattr(config, "LOCK_GPIO_ENABLED", True)
    monkeypatch.setitem(sys.modules, "gpiod", None)

    controller = build_lock_controller()
    assert isinstance(controller, NoopLockController)
    controller.unlock()
    controller.close()


def _fake_gpiod(events):
    class FakeValue:
        ACTIVE = "active"
        INACTIVE = "inactive"

    class FakeDirection:
        OUTPUT = "output"

    class FakeLineSettings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeRequest:
        def set_value(self, line, value):
            events.append(("set", line, value))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            events.append(("close",))

    class FakeGpiod:
        LineSettings = FakeLineSettings

        def request_lines(self, chip_path, *, consumer, config):
            events.append(("request", chip_path, consumer, config))
            return FakeRequest()

    return FakeGpiod(), FakeDirection, FakeValue


def test_gpio_lock_controller_pulses_active_low_line():
    from app.lock_controller import GpioLockController

    events = []
    sleeps = []
    fake_gpiod, fake_direction, fake_value = _fake_gpiod(events)

    controller = GpioLockController(
        "/dev/gpiochip0",
        "PC11",
        active_low=True,
        unlock_ms=2000,
        gpiod_module=fake_gpiod,
        direction=fake_direction,
        value=fake_value,
        sleep=sleeps.append,
    )

    controller.unlock()

    assert events[0][:3] == ("request", "/dev/gpiochip0", "palmgate-lock")
    settings = events[0][3]["PC11"]
    assert settings.kwargs == {
        "direction": "output",
        "active_low": True,
        "output_value": "inactive",
    }
    assert sleeps == [2.0]
    assert events[1:] == [
        ("set", "PC11", "active"),
        ("set", "PC11", "inactive"),
        ("close",),
    ]


def test_gpio_lock_controller_turns_relay_off_if_sleep_fails():
    from app.lock_controller import GpioLockController

    events = []
    fake_gpiod, fake_direction, fake_value = _fake_gpiod(events)

    def fail_sleep(seconds):
        raise RuntimeError("sleep failed")

    controller = GpioLockController(
        "/dev/gpiochip0",
        "PC11",
        active_low=True,
        unlock_ms=2000,
        gpiod_module=fake_gpiod,
        direction=fake_direction,
        value=fake_value,
        sleep=fail_sleep,
    )

    with pytest.raises(RuntimeError, match="sleep failed"):
        controller.unlock()

    assert events[-2:] == [
        ("set", "PC11", "inactive"),
        ("close",),
    ]
