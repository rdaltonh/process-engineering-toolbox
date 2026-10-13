# Phase 0 — Fast-Track Foundation Spec

**Status:** Built 2026-10-12. Materials data is sourced from B31.3 App. C (from memory, unverified) rather than NIST, since the v1 range is −40 to +300°F. CoolProp is not yet used (contents via SG).
**Revised:** 2026-10-12. Trimmed to what the launcher and Span Chart need. FOSS only, no MATLAB.
**Roadmap reference:** `docs/ROADMAP.md`, Section 5

---

## 1. Goal

Get the launcher/frontend running and give the Span Chart (`span-chart.md`) everything it needs from `core`. Nothing else gets built yet. The Span Chart's save/load round-trip test replaces the throwaway dummy app.

## 2. Decisions locked in

| Topic | Decision |
|---|---|
| Repo | Monorepo at `C:\dev\Tools\process-engineering-toolbox`, git-initialized |
| Tooling | FOSS only: Python 3.14, Streamlit (Apache-2.0), NumPy/SciPy (BSD), Plotly (MIT), pint (BSD), CoolProp (MIT), pytest (MIT). No MATLAB |
| Frontend | Streamlit. A single launcher process uses `st.navigation`, and each app also runs standalone |
| Packaging | `core/` installable as `proctoolbox_core` via `pip install -e .` |
| Storage | JSON project files (roadmap Section 3.3) |

## 3. Deliverables

### 3.1 Repository scaffold
- The roadmap Section 3.2 layout, with stub `app.py` + `README.md` + `app.toml` for every listed app.
- `pyproject.toml` (pinned deps), `.gitignore`, `README.md`, `docs/CONTRIBUTING.md` (roadmap Section 6), `tests/`.

### 3.2 Launcher / frontend
- `launcher/app.py` provides a home page with six category cards, each listing its apps and their status (Available / Stub / Planned).
- A sidebar with grouped navigation by category, via `st.navigation({category: [pages]})`.
- **App discovery:** the launcher scans `apps/*/*/app.toml` (`name`, `category`, `status`, `entry`, `description`), so adding an app never requires editing the launcher.
- Every `app.py` also runs standalone: `streamlit run apps/<category>/<app>/app.py`.
- Stub apps render "Not yet implemented" with their roadmap note.
- Shared page chrome (title and placeholder-warning banner) comes from `core.ui`, so every app looks consistent.
- A launch script: `run.ps1` / `run.sh` → `streamlit run launcher/app.py`.

### 3.3 `core.units`
- A shared pint `ureg`, plus `Q_()` and `convert()`.
- Units covered: in/mm/ft/m, lb/kg, lbf/N, psi/ksi/MPa, lb/ft·kg/m (line weight), °F/°C/K, in⁴/mm⁴, in³/mm³.
- Gauge vs absolute pressure stays explicit (only needed for the contents-density lookup).
- The UI offers a US-customary / SI display toggle. Calculations run internally in SI.

### 3.4 `core.io` — project files
- The roadmap Section 3.3 structure: `save()` / `load()` with validation, and units serialized as `{value, unit}`.
- `schema_version` "1.0", with an empty migration registry. An unknown newer version raises an error.
- Structured warnings `{code, message, source}` in `metadata.warnings`.

### 3.5 `core.ui`
- `page_header(app_meta)`, `warning_banner(warnings)`, `save_load_panel(...)` (JSON download/upload, plus save to the app's `projects/` folder), and `unit_system_toggle()`.

### 3.6 `core.piping.dimensions` — pipe dimensional data
- NPS ½″–24″, carbon/alloy schedules (ASME B36.10M) and stainless schedules (ASME B36.19M, 5S/10S/40S/80S).
- Fields: OD and nominal wall. ID, metal area, flow area, I, and Z are **computed** from those, not tabulated.
- These are published dimensional standards, not safety allowables. Every entry carries a citation to the standard. Dalton spot-checks the table before Span Chart v1 is marked done, and a test pins a sample of known values.
- Dimension data lives in `core/piping/data/pipe_dimensions.json`, not in code.

### 3.7 `core.materials` — Materials Engine v1 (minimum)
- The data model from the original spec: `curve_fit` / `tabular` / `placeholder` property kinds, a citation on every value, an error on out-of-range T unless extrapolation is opted into (and an opted-in extrapolation still warns), and placeholders that always return `is_placeholder=True` plus a warning.
- **Properties in v1:** elastic modulus E(T) and density only (what the Span Chart needs).
- **Materials:** 304 SS, 316/316L SS, and 5083-O Al from public-domain NIST cryogenic data where published. Any gap becomes a placeholder.
- **Custom material:** the user enters E (and optionally E at T), density, and a free-text source. The user-supplied source is recorded as the citation.
- Allowable stress is **not** in the engine for v1. The Span Chart takes it as a user input (see its spec).
- `neutron_degradation.py` is an interface stub.

### 3.8 `core.fluids` (minimum)
- `density(fluid, P, T)` and `saturated_liquid_density(fluid, P|T)` via CoolProp, used for pipe contents. Typed `FluidStateError`.
- The full `FluidState` wrapper is deferred to Phase 2.

## 4. Acceptance criteria
1. `pip install -e .` works on a clean Python 3.14 venv.
2. `pytest` passes: units, io round-trip, unknown-version rejection, pipe-dimension spot values, materials range/placeholder behavior, and CoolProp density spot checks.
3. `streamlit run launcher/app.py` shows six categories, the stub apps, working sidebar navigation, and the Span Chart reachable.
4. No ASME allowable or other unsourced safety value appears in code or data.

## 5. Deferred (Phase 2+)
- The full CoolProp wrapper, k/cp/CTE/thermal-strain properties, neutron modeling, the calc-package reporter, and recent-projects/search in the launcher.

## 6. Risks
- **Python 3.14 is new.** If a dependency lacks wheels, fall back to a 3.12 venv and flag it.
- **NIST modulus coverage is sparse for some alloys.** Gaps become placeholders, and the Span Chart then requires the user to enter E.
