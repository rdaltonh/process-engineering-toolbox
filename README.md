# Process Engineering Toolbox

Self-hosted, FOSS-only suite of engineering calculation apps for cryogenic and general process engineering. Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md).

## Setup
```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Run
```
.\run.ps1          # or: .venv\Scripts\streamlit run launcher\app.py
```
Opens at http://localhost:8501, bound to localhost with telemetry off (`.streamlit/config.toml`). Any app also runs standalone, e.g. `streamlit run apps/piping_structural/span_chart/app.py`.

## Desktop app (Windows)
```
powershell -ExecutionPolicy Bypass -File desktop\Install.ps1
```
This creates `.venv` if it is missing and adds **Process Engineering Toolbox** shortcuts to the Desktop and Start menu. The shortcut starts the server hidden and opens the toolbox in its own window (Edge/Chrome app mode). Closing the window stops the server, unless it was already running when you launched. The server log is in `%LOCALAPPDATA%\ProcessToolbox\server.log`.

Updating needs no reinstall: the shortcut runs the repo in place, so after a `git pull` you just relaunch. The **Update toolbox** button at the bottom of the sidebar runs that pull (fast-forward only) for you and lists the new commits. If `pyproject.toml` has changed, the launcher re-runs `pip install -e ".[dev]"` (in a console window, log at `%LOCALAPPDATA%\ProcessToolbox\pip.log`) before it starts the server. To remove the shortcuts, run `Install.ps1 -Uninstall`. The icon comes from `desktop/make_icon.py`.

## Test
```
.venv\Scripts\python -m pytest
```

## Layout
- `core/`: shared package `proctoolbox_core`: units (pint), project-file I/O, Streamlit UI widgets, pipe dimensions, Materials Engine.
- `launcher/`: home screen. It discovers apps from `apps/<category>/<app>/app.toml`.
- `apps/`: one folder per app (`app.py`, `app.toml`, `README.md`, `projects/`). Apps import only from `core`, never from each other.
- `docs/`: roadmap, contributor standards, app specs, data verification checklist.

## Adding an app
1. Write `docs/app-specs/<app>.md` and get it confirmed.
2. Create `apps/<category>/<app>/` with `app.toml` (id, name, category, status, version, entry, description), `app.py`, `README.md`, and `projects/.gitkeep`.
3. The launcher picks it up automatically.

## Data status
Material properties and pipe dimensions are currently **unverified** (entered from memory), and the apps say so. See [docs/DATA-VERIFICATION.md](docs/DATA-VERIFICATION.md).
