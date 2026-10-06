# Repository Guidelines

## Project Structure & Module Organization

- `app/`: FastAPI backend. `main.py` manages startup/shutdown; `routes/` exposes endpoints; `services/` contains recognition and enrollment logic. Camera workers, GPIO, SQLite, and inference live in dedicated modules.
- `frontend/app/`: React/TypeScript dashboard using TanStack Start and Vite; components, routes, and browser utilities have separate directories.
- `tests/`: Python regression tests. Frontend tests sit beside source files as `*.test.ts`.
- `app/static/`: legacy dashboard and vendored MediaPipe assets. Keep `frontend/app/styles.css` identical to `app/static/style.css`; a parity test enforces this.
- `model.tflite`: fixed runtime model. Read `CONTEXT.md` for domain vocabulary and `README.md` for hardware setup.

## Build, Test, and Development Commands

Use Python 3.10+ in an activated virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
APP_DEBUG=true python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Provide root `hand_landmarker.task` and vendored browser assets as documented in README.

In another terminal, run `cd frontend` and `bun install --frozen-lockfile`. Then:

- `bun run dev`: dashboard at `http://localhost:3000`, proxying API requests to port 8000.
- `bun run test`: Vitest suite; component tests use jsdom.
- `bun run build`: synchronize browser assets and build production output.
- From repository root, `python -m pytest tests/ -q`: backend suite.

## Coding Style & Naming Conventions

Use four-space Python indentation and `snake_case` functions/modules. Match existing TypeScript conventions: two-space indentation, single quotes, no semicolons, `PascalCase` components, and `camelCase` functions. No dedicated formatter or lint command is configured. Keep changes focused; reuse existing helpers and standard-library facilities. Preserve interpreter isolation, MediaPipe/CLAHE locks, and three-rotation TTA.

## Testing Guidelines

Name Python tests `test_*.py` with `test_*` functions. Add meaningful regression tests for behavior changes, especially concurrency and hardware isolation. Run targeted tests, then relevant suites and the frontend build. No coverage percentage is enforced; report baseline failures separately from regressions.

## Commit & Pull Request Guidelines

Use concise imperative commits with existing prefixes: `feat:`, `fix:`, `docs:`, `chore:`, or `refactor:`. Describe resulting behavior, link relevant issues, and list validation results in PRs. Include screenshots for layout changes and identify hardware checks that remain unverified.

## Configuration & Data Safety

Copy `.env.example` to `.env`; never commit secrets or runtime captures. `APP_DEBUG=true` defaults to browser input and disables GPIO. Non-debug USB operation requires `APP_DEBUG=false`; GPIO additionally requires `LOCK_GPIO_ENABLED=1`. Keep Compose profiles consistent with the mode. Respect `DB_PATH`; database resets delete users and logs.
