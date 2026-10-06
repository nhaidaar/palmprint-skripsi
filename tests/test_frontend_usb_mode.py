from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "app"


def read_component(name):
    return (FRONTEND / "components" / name).read_text()


def test_frontend_checks_status_before_starting_browser_camera():
    source = read_component("ScanPanel.tsx")

    assert "/api/status" in source
    assert "data.app?.camera_source === 'usb'" in source
    assert "navigator.mediaDevices.getUserMedia" in source


def test_frontend_streams_usb_preview_without_browser_camera():
    source = read_component("ScanPanel.tsx")

    assert "const USB_PREVIEW_STREAM_URL = '/api/device-registration/preview.mjpg'" in source
    assert "?direction=ENTRY" in source
    assert "?direction=EXIT" in source
    assert "URL.createObjectURL" not in source


def test_usb_workers_own_scanning_without_manual_browser_duplicates():
    source = read_component("ScanPanel.tsx")

    assert "if (busyRef.current || usbDeviceMode) return" in source
    assert "!usbDeviceMode && <>" in source
    assert "scan-events?direction=${direction}" in source


def test_registration_ui_requires_and_sends_nim():
    source = read_component("RegisterPanel.tsx")

    assert "NIM and full name are required" in source
    assert "body: JSON.stringify({ nim, name" in source


def test_registration_ui_has_optional_hand_chips():
    source = read_component("RegisterPanel.tsx")

    assert "selectedHands" in source
    assert "function toggleHand(hand: Hand)" in source
    assert "left" in source
    assert "right" in source


def test_browser_registration_sends_hand_labels_and_full_frames():
    source = read_component("RegisterPanel.tsx")

    assert "REGISTRATION_CAPTURES_PER_HAND = 5" in source
    assert "hands: samples.map((sample) => sample.hand)" in source
    assert "images: samples.map((sample) => sample.image)" in source
    assert "is_roi: false" in source


def test_usb_registration_uses_existing_device_endpoints():
    source = read_component("RegisterPanel.tsx")

    assert "/api/device-registration/start" in source
    assert "/api/device-registration/status" in source
    assert "/api/device-registration/capture" in source
    assert "/api/device-registration/finalize" in source
    assert "/api/device-registration/cancel" in source
    assert "hands: selectedHands" in source


def test_upload_registration_is_dev_only_and_sends_upload_source():
    source = read_component("RegisterPanel.tsx")

    assert "hidden={!devFeatures}" in source
    assert "source: 'upload'" in source
    assert "is_roi: false" in source


def test_scan_panel_has_dev_upload_and_roi_preview_ui():
    source = read_component("ScanPanel.tsx")

    assert "id=\"scanUploadFile\"" in source
    assert "debug_roi: devFeatures" in source
    assert "roiPreviewImage" in source


def test_frontend_displays_nim_with_user_name():
    source = read_component("UserList.tsx")

    assert "{user.nim}" in source
    assert "{user.name}" in source
