import re
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


def test_compose_runs_one_shared_stack_without_hardware_or_tunnel():
    compose = Path("docker-compose.yml").read_text()

    services = compose.split("services:\n", 1)[1].split("\nvolumes:", 1)[0]
    assert set(re.findall(r"^  ([\w-]+):", services, re.MULTILINE)) == {
        "palmgate-api", "palmgate-frontend", "palmgate-proxy",
    }
    assert "PALMGATE_API_UPSTREAM=http://palmgate-api:8000" in compose
    assert "PALMGATE_FRONTEND_UPSTREAM=http://palmgate-frontend:3000" in compose
    assert "profiles:" not in compose
    assert "cloudflare" not in compose.lower()
    assert "devices:" not in compose


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
    frontend_common = compose[compose.index("  palmgate-frontend:") : compose.index("  palmgate-proxy:")]

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
