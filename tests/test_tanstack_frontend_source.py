from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_tanstack_frontend_exists_without_zustand():
    package_json = (FRONTEND / "package.json").read_text()

    assert "@tanstack" in package_json
    assert "zustand" not in package_json.lower()


def test_frontend_dev_proxy_targets_fastapi_api():
    vite_config = "\n".join(path.read_text() for path in FRONTEND.glob("vite.config.*"))

    assert "'/api'" in vite_config or '"/api"' in vite_config
    assert "http://127.0.0.1:8000" in vite_config


def test_frontend_keeps_three_dashboard_tabs():
    index = (FRONTEND / "app" / "routes" / "index.tsx").read_text()

    assert "'scan'" in index
    assert "'register'" in index
    assert "'log'" in index
    assert "<ScanPanel" in index
    assert "<RegisterPanel" in index
    assert "<LogPanel" in index


def test_log_panel_uses_filter_count_and_export_endpoints():
    source = (FRONTEND / "app" / "components" / "LogPanel.tsx").read_text()

    assert "/api/logs" in source
    assert "/api/logs/count" in source
    assert "/api/logs/export.xlsx" in source
    assert "/api/logs/export.csv" not in source
    assert "Export Excel" in source
    assert "filtersActive" in source
    assert "Access log filters" in source
    assert "Search name, NIM, or description" in source
    assert "type=\"date\"" in source
    assert "nextLogFilters" in source
    assert "latestRequestRef" in source
    assert "setTimeout" in source


def test_frontend_config_installs_api_proxy_before_nitro():
    vite_config = (FRONTEND / "vite.config.ts").read_text()
    package_json = (FRONTEND / "package.json").read_text()

    assert "configureServer" in vite_config
    assert "enforce: 'pre'" in vite_config
    assert vite_config.index("palmgateApiProxy(),") < vite_config.index("tanstackStart({")
    assert '"nitro": "3.0.260311-beta"' in package_json


def test_mediapipe_public_module_uses_absolute_runtime_url():
    source = (FRONTEND / "app" / "lib" / "mediapipe.ts").read_text()

    assert "new URL(VISION_BUNDLE_URL, window.location.href).href" in source


def test_register_panel_handles_usb_polling_cancel_and_disabled_states():
    source = (FRONTEND / "app" / "components" / "RegisterPanel.tsx").read_text()

    assert "refreshUsbStatus().catch" in source
    assert "USB status refresh failed" in source
    assert "Cancel failed" in source
    assert "upload-picker" in source and "disabled" in source
    assert "registrationQualityClass" in source


def test_scan_panel_uses_backend_version_and_closes_hand_landmarker():
    source = (FRONTEND / "app" / "components" / "ScanPanel.tsx").read_text()

    assert "setAppVersion(data.app?.version" in source
    assert "handLandmarker.close" in source
    assert "id=\"appVersion\">{appVersion}" in source


def test_user_list_uses_edit_and_delete_endpoints_with_typed_nim_guard():
    source = (FRONTEND / "app" / "components" / "UserList.tsx").read_text(encoding="utf-8")

    assert "method: 'PATCH'" in source
    assert "method: 'DELETE'" in source
    assert "canDeleteUser(deleteText, deleteUser.nim)" in source
    assert "const deleteBusyRef = useRef(false)" in source
    assert "deleteBusyRef.current = true" in source
    assert "deleteBusyRef.current = false" in source
    assert "setDeleting(true)" in source
    assert "setDeleting(false)" in source
    assert "Deleting…" in source
    assert "aria-busy={deleting}" in source
    assert "disabled={deleting}" in source
    assert "Historical logs stay" in source
    assert "Failed to update user" in source
    assert "Failed to delete user" in source

    delete_handler = source[source.index("const removeUser"):]
    delete_catch = delete_handler[delete_handler.index("} catch (err) {"):delete_handler.index("} finally {")]
    assert delete_catch.index("await loadUsers()") < delete_catch.index("setError(")


def test_scan_panel_keeps_browser_and_usb_scan_endpoints():
    source = (FRONTEND / "app" / "components" / "ScanPanel.tsx").read_text()

    assert "/api/status" in source
    assert "/api/recognize" in source
    assert "/api/device-registration/preview.mjpg" in source
    assert "/api/device-registration/scan-events" in source
    assert "debug_roi" in source
    assert "is_roi: false" in source


def test_register_panel_keeps_guided_registration_endpoints():
    source = (FRONTEND / "app" / "components" / "RegisterPanel.tsx").read_text()

    assert "/api/register" in source
    assert "/api/device-registration/start" in source
    assert "/api/device-registration/status" in source
    assert "/api/device-registration/capture" in source
    assert "/api/device-registration/finalize" in source
    assert "/api/device-registration/cancel" in source
    assert "REGISTRATION_CAPTURES_PER_HAND" in source
    assert "hands" in source


def test_fastapi_no_longer_serves_legacy_dashboard():
    source = (ROOT / "app" / "main.py").read_text()

    assert "StaticFiles" not in source
    assert "static/index.html" not in source
    assert "@app.get(\"/\")" not in source


def test_user_changes_trigger_log_refresh():
    index = (FRONTEND / "app" / "routes" / "index.tsx").read_text()
    log_panel = (FRONTEND / "app" / "components" / "LogPanel.tsx").read_text()
    user_list = (FRONTEND / "app" / "components" / "UserList.tsx").read_text()

    assert "const [logRefreshKey, setLogRefreshKey]" in index
    assert "refreshKey={logRefreshKey}" in index
    assert "onUsersChanged={refreshLogs}" in index
    assert "refreshKey" in log_panel
    assert "onUsersChanged" in user_list
    assert "onUsersChanged?.()" in user_list


def test_scan_panel_has_guidance_overlay_and_hold_timer():
    source = (FRONTEND / "app" / "components" / "ScanPanel.tsx").read_text()

    assert "const SCAN_HOLD_MS" in source
    assert "requestAnimationFrame(detectLoop)" in source
    assert "detectForVideo" in source
    assert "overlayRef" in source
    assert "drawHandOverlay" in source
    assert "holdStartRef" in source
    assert "autoMode" in source
    assert "Palm detected" in source


def test_register_panel_has_guidance_hold_and_cooldown():
    source = (FRONTEND / "app" / "components" / "RegisterPanel.tsx").read_text()

    assert "const REG_HOLD_MS" in source
    assert "const REG_COOLDOWN_MS" in source
    assert "requestAnimationFrame(detectLoop)" in source
    assert "detectForVideo" in source
    assert "overlayRef" in source
    assert "registrationQualityLine" in source
    assert "captureBrowserSample()" in source
    assert "cooldownUntilRef" in source
