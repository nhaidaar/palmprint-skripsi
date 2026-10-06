from pathlib import Path


def test_frontend_has_bun_dockerfile_running_tanstack_start():
    source = Path("frontend/Dockerfile").read_text()

    assert "FROM oven/bun:1" in source
    assert "bun install --frozen-lockfile" in source
    assert "bun run build" in source
    assert "EXPOSE 3000" in source
    assert 'CMD ["bun", ".output/server/index.mjs"]' in source
    assert "npm ci" not in source
    assert "npm run build" not in source
    assert 'CMD ["node", ".output/server/index.mjs"]' not in source


def test_nginx_proxy_routes_frontend_and_api_streams():
    source = Path("deploy/nginx/palmgate.conf").read_text()

    assert "proxy_pass http://palmgate-frontend:3000" in source
    assert "proxy_pass http://palmgate-api:8000" in source
    assert "location /api/" in source
    assert "proxy_buffering off" in source
    assert "X-Accel-Buffering" in source


def test_compose_runs_api_frontend_and_proxy_for_profiles():
    compose = Path("docker-compose.yml").read_text()

    assert "palmgate-api-browser:" in compose
    assert "palmgate-api-usb:" in compose
    assert "palmgate-frontend-browser:" in compose
    assert "palmgate-frontend-usb:" in compose
    assert "palmgate-proxy-browser:" in compose
    assert "palmgate-proxy-usb:" in compose
    assert "PALMGATE_API_UPSTREAM=http://palmgate-api-browser:8000" in compose
    assert "PALMGATE_API_UPSTREAM=http://palmgate-api-usb:8000" in compose
    assert "PALMGATE_FRONTEND_UPSTREAM=http://palmgate-frontend-browser:3000" in compose
    assert "PALMGATE_FRONTEND_UPSTREAM=http://palmgate-frontend-usb:3000" in compose
    assert "cloudflared-browser:" in compose
    assert "palmgate-proxy-browser" in compose
    assert "cloudflared-usb:" in compose
    assert "palmgate-proxy-usb" in compose


def test_dockerignore_keeps_frontend_source_but_ignores_node_artifacts():
    source = Path(".dockerignore").read_text()
    frontend_source = Path("frontend/.dockerignore").read_text()

    assert "frontend/" not in source.splitlines()
    assert "frontend/node_modules" in source
    assert "frontend/.output" in source
    assert "node_modules" in frontend_source
    assert ".output" in frontend_source


def test_compose_uses_prebuilt_frontend_image_by_default():
    compose = Path("docker-compose.yml").read_text()
    frontend_common = compose[compose.index("x-frontend-common:") : compose.index("x-proxy-common:")]

    assert "image: ${PALMGATE_FRONTEND_IMAGE:-ghcr.io/nhaidaar/palmprint-fe:latest}" in frontend_common
    assert "build:" in frontend_common


def test_github_actions_publishes_frontend_ghcr_image():
    workflow = Path(".github/workflows/docker.yml").read_text()

    assert "FRONTEND_IMAGE_NAME: ghcr.io/nhaidaar/palmprint-fe" in workflow
    assert "context: ." in workflow
    assert "file: frontend/Dockerfile" in workflow
    assert "${{ env.FRONTEND_IMAGE_NAME }}:latest" in workflow
    assert "${{ env.FRONTEND_IMAGE_NAME }}:${{ env.SHORT_SHA }}" in workflow


def test_env_example_documents_prebuilt_frontend_image():
    env_example = Path(".env.example").read_text()

    assert "PALMGATE_FRONTEND_IMAGE=ghcr.io/nhaidaar/palmprint-fe:latest" in env_example
