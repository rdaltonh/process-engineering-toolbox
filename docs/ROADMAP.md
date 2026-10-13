# Process Engineering Toolbox — System Roadmap & Implementation Guide

**Audience:** This document is written for a team of AI agents (Claude instances) picking up implementation work on this system over time, in addition to Dalton (Robert Dalton Hicks), the engineer for whom it's being built. Read Section 6 before writing any code.

---

## 1. Vision & Purpose

The Process Engineering Toolbox is a personal suite of standalone engineering calculation applications for cryogenic and general process engineering work — vacuum vessel design, refrigeration cycle modeling, piping structural analysis, fluid line sizing, and related disciplines. It replaces ad hoc Excel workbooks and commercial software (e.g. Hysys) with purpose-built, maintainable, self-hosted tools that encode engineering procedures (primarily ASME and related codes) programmatically.

This is **not** one monolithic application. It's a collection of independent apps, organized into six categories, sharing a common foundation so they behave consistently without being tightly coupled to each other.

**The six categories:**
1. Piping Structural
2. Fluid Analysis & Design
3. Component Design & Material Choice
4. Thermodynamic Design
5. Process Hazards Analysis
6. Project Management & Costing

---

## 2. Guiding Principles

These carry over from how this tooling has been built so far and apply to all future work on the suite:

- **Self-hostable, no cloud dependencies.** Every app runs locally. No external services required for core functionality.
- **Class-based architecture over scripts.** Encode engineering procedures as classes with clear state, not procedural scripts.
- **Safety-critical placeholder discipline (hard rule).** Never fabricate a plausible-looking ASME table value, material property, or chart digitization. If the true source data isn't available, ship a clearly labeled placeholder with a prominent warning instead. This has already been done correctly once (vacuum vessel tool's Figure G / HA-1 chart data) — replicate that pattern, don't relax it.
- **Schema-first discipline.** Before modifying any code that depends on a data model (database schema, config file format), audit what's actually on disk. A prior schema drift bug in the procurement tool came directly from skipping this step.
- **Scope before building.** For every new app, produce a short spec and get it confirmed before writing implementation code. Front-loaded clarification (material basis, head types, component ordering, etc.) has already prevented costly rework twice.
- **FOSS only — no MATLAB (revised 2026-10-12).** All development, prototyping, and testing happens in free/open-source tooling (Python, NumPy/SciPy, Matplotlib/Plotly, Streamlit, CoolProp, pint). MATLAB is not used in any workflow. The existing MATLAB tools (`VacuumVesselDesigner`, RCA toolbox) are treated only as *reference source text*, read to understand the validated logic and then reimplemented in Python. No MATLAB execution is required. Regression cases come from previously saved MATLAB outputs (if any exist) or independent hand calculations.
- **Open source / free tooling only.** No paid or licensed dependencies. CoolProp is the fluid-property library for all apps — REFPROP is out of scope entirely, not just deprioritized.
- **No forced uniformity in storage.** Apps are standalone enough that they don't need to share a storage mechanism. The procurement tracker's SQLite backend stays as-is; other apps default to the JSON project-file pattern (Section 3.3) unless a given app has a specific reason to do otherwise. Consistency across apps matters for UX (save/load feel, warning banners) and for the `core` package's shared logic — not for the underlying storage format.

---

## 3. System Architecture

### 3.1 High-Level Concept

A suite of independent Streamlit apps, one per tool, organized under category folders, all importing from one shared Python core package. A lightweight launcher presents the six categories and the apps within each. Each app manages its own saved project files independently — there is no shared project state across apps.

### 3.2 Repository Layout

```
process-engineering-toolbox/
├── core/                              # shared package: proctoolbox_core
│   ├── __init__.py
│   ├── materials/
│   │   ├── database.py                # property lookups, curve fits, citations
│   │   ├── data/                      # source CSVs/JSON — NIST cryo data, ASME tables
│   │   └── neutron_degradation.py     # fluence-adjusted property modifiers
│   ├── fluids/
│   │   └── coolprop_wrapper.py        # unified fluid property interface
│   ├── units/
│   │   └── convert.py
│   ├── io/
│   │   ├── config_schema.py           # versioned JSON project-file schema
│   │   └── project_file.py            # save/load/validate
│   ├── ui/
│   │   └── components.py              # shared widgets: material picker, save/load, export
│   └── reporting/
│       └── calc_package.py            # ASME calc-package / report generator
├── launcher/
│   └── app.py                         # Streamlit home screen, organized by category
├── apps/
│   ├── piping_structural/
│   │   ├── span_chart/
│   │   └── expansion_loop/
│   ├── fluid_analysis_design/
│   │   └── line_sizing_jt/
│   ├── component_design_material/
│   │   └── vacuum_vessel_designer/
│   ├── thermodynamic_design/
│   │   └── turbo_brayton_designer/
│   ├── process_hazards_analysis/
│   │   └── (unscoped — see Section 5, Phase 4)
│   └── project_management_costing/
│       └── procurement_tracker/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CONTRIBUTING.md                # this document's standards, kept in-repo
│   └── app-specs/                     # one spec per app, written before build starts
├── tests/
└── requirements.txt
```

**Rules for this layout:**
- Each app folder is standalone: its own `app.py` (Streamlit entry point), its own `projects/` directory for saved files, its own `README.md`.
- Apps import from `core`. Apps never import from other apps.
- All shared logic — material properties, fluid properties, units, config I/O, reporting — lives in `core` exactly once.

### 3.3 Project/Config File Standard

Every app saves and loads its work using a common JSON structure:

```json
{
  "schema_version": "1.0",
  "app_name": "vacuum_vessel_designer",
  "app_version": "0.1.0",
  "created": "ISO-8601 timestamp",
  "modified": "ISO-8601 timestamp",
  "inputs": { },
  "results": { },
  "metadata": {
    "warnings": [ ],
    "material_citations": [ ]
  }
}
```

- `schema_version` allows future migration without breaking old project files.
- `metadata.warnings` is where placeholder-data flags live (e.g. "Figure G chart data not yet digitized from Dalton's Code edition").
- Every app must round-trip save → load without data loss before being considered done.

### 3.4 Materials Property Engine (build first — everything downstream depends on it)

Single source of truth for temperature-dependent material properties, queried by Component Design, Piping Structural, and Thermodynamic Design apps alike. Needs:
- Elastic modulus, CTE, yield/UTS, thermal conductivity, specific heat — as functions of temperature
- A source-citation field per data point (ASME Section II Part D, NIST cryogenic databases, etc.)
- Curve-fitting/interpolation utilities
- The placeholder + warning mechanism described in Section 2, built in from the start rather than bolted on later
- An extension point for neutron-fluence-adjusted properties (relevant to Dalton's cryogenic/neutron-service material selection work — vanadium alloys, low-cobalt 316L, 5083 aluminum have already come up)

### 3.5 Fluid Property Layer

A thin, consistent wrapper around CoolProp — the sole fluid-property backend for the suite (open-source only; REFPROP is not used). Used by the line-sizing tool, the Brayton cycle tool, and any future process simulation work — one interface, not one per app.

### 3.6 Reporting / Calc Package Generator

Takes any app's saved project file plus its material citations and assembles a stamped-ready calculation package (Word/PDF), replacing manual report assembly. Built once in `core`, used by every app.

---

## 4. App Inventory & Status

| Category | App | Status | Notes |
|---|---|---|---|
| Piping Structural | Span Chart | New — **first priority** | Calculated support spacing (beam theory, B31.3-consistent); VJ deferred to v2 |
| Piping Structural | Expansion Loop | New | Guided-cantilever sizing, bellows-vs-loop decision logic |
| Fluid Analysis & Design | Real-Gas Line/JT Sizing | New | Encodes intermediate-back-pressure JT insight as a core parameter |
| Component Design & Material Choice | Vacuum Vessel Designer | Existing (MATLAB source, reference only) | `VacuumVesselDesigner` class, UG-28/29/33; reimplement in Python |
| Component Design & Material Choice | Materials Property Engine | New, foundational | Section 3.4 — build before porting vessel tool |
| Thermodynamic Design | Turbo-Brayton / Collins Cycle Designer | Existing (MATLAB source, "RCA" toolbox, reference only) | `TurboBraytonDesigner` class, Gauss-Seidel solver; reimplement in Python |
| Thermodynamic Design | Process Simulation Tool | Unconfirmed / future | Narrow-scope Hysys alternative, CoolProp-based; interest stated, not yet scoped |
| Process Hazards Analysis | *(none yet)* | Unscoped | Relief/venting sizing is the leading candidate |
| Project Management & Costing | Procurement Tracker | Existing (Python/Streamlit/SQLite) | Already built; needs restructuring into suite layout only |

---

## 5. Phased Roadmap

### Phase 0 — Fast-track foundation (revised 2026-10-12)
Only the `core` pieces the launcher and Span Chart need. Spec: `docs/app-specs/phase-0-foundation.md`.
1. Scaffold the repository per Section 3.2.
2. Launcher/frontend shell (Streamlit), with all six categories and stub apps.
3. `core` minimum: units, project-file I/O, save/load + warning-banner UI, pipe dimensions, Materials Engine v1 (E(T), density), and a minimal CoolProp density lookup for pipe contents.

### Phase 1 — Span Chart (first real app)
Spec: `docs/app-specs/span-chart.md`. Calculated spans (beam theory, B31.3-consistent) for bare/insulated single pipe. VJ pipe deferred to a later Span Chart revision. Span Chart is also the end-to-end validation of the project-file round-trip (replaces the throwaway dummy app).

### Phase 2 — Remaining core + migrations + new tools (order to be set with Dalton)
- Complete the CoolProp wrapper and the remaining materials properties (k, cp, CTE/thermal strain).
- **Procurement Tracker:** restructure into `apps/project_management_costing/`. This is a layout change, not a rewrite. Preserve the existing SQLite schema as-is.
- **Vacuum Vessel Designer (reimplement in Python from MATLAB source as reference):** preserve UG-28/29/33 procedures, the bisection thickness solve (→ `scipy.optimize.brentq`), and the placeholder-chart-data pattern with its warnings, verbatim.
- **Turbo-Brayton / RCA Toolbox (reimplement in Python from MATLAB source as reference):** preserve the Gauss-Seidel solver, arbitrary component sequencing, recuperator pairing, and the JT-branch intermediate-back-pressure targeting logic.
- **Span Chart v2:** VJ pipe (jacket span + inner-line spacer span), with a cryo-vs-non-cryo property branch (some austenitic steels' modulus rises at cryogenic T, so don't assume monotonic behavior).
- **Expansion Loop:** guided-cantilever sizing, CTE integrated across 293 K → 4 K, and a bellows-vs-loop decision branch for VJ transfer lines.
- **Real-Gas Line & JT Sizing:** single- and two-phase helium via CoolProp, with intermediate-back-pressure JT targeting as a first-class input.

### Phase 3 — Reporting & cross-suite polish
1. Build the Calc Package Reporter (Section 3.6).
2. Consistency pass across all apps: shared save/export UX, shared warning/placeholder banner styling.
3. Launcher polish: recent-projects view, search/filter across the suite.

### Phase 4 — Unscoped / requires Dalton's input before starting
1. **Process Hazards Analysis category:** no app defined yet. Relief/venting sizing is the leading candidate but needs a scoping conversation first.
2. **Cryogenic Process Simulation Tool:** confirmed interest, no committed scope. Would live under Thermodynamic Design once defined.
3. **Neutron-fluence-aware material degradation modeling:** extend the Materials Property Engine once Dalton's cryogenic/neutron-service material selection work matures further.

---

## 6. Standards for Agentic Contributors

Read this before writing code, whichever piece of the roadmap you've been asked to work on.

- **Never fabricate safety-relevant values.** Vessel thickness, allowable stress, span limits, pressure ratings — if the governing table or chart value isn't from a verifiable source (ASME Section VIII, B31.3, NIST cryogenic data, or a value Dalton supplies directly), insert a clearly marked placeholder with an inline warning. This is not a style preference; treat it as a hard constraint.
- **Write a spec before building.** For any new app, produce `docs/app-specs/<app-name>.md` covering governing code/reference, inputs, outputs, known limitations, and open questions — and get it confirmed before writing the app.
- **Audit the actual schema before touching dependent code.** Check what's really on disk (database schema, config format) before modifying anything that reads or writes it.
- **Keep apps standalone.** No app imports another app's code — only `core`.
- **Preserve validated engineering logic when porting.** The UG-28/29/33 bisection solve, the Gauss-Seidel cycle solver, and the JT intermediate-pressure-targeting logic are already validated against real analysis. Port them faithfully. If you think the engineering approach itself should change, flag it explicitly for Dalton's review rather than changing it silently during a port.
- **Document as you build.** Every app gets a `README.md`: purpose, governing code/reference, inputs/outputs, known limitations, current placeholder/TODO items.
- **Regression tests without MATLAB.** Where saved MATLAB outputs exist for an input set, use them as test cases for the Python reimplementation. Otherwise use independent hand calculations. Never run MATLAB.

---

## 7. Tech Stack Reference

- **Language/runtime:** Python 3.x
- **UI:** Streamlit
- **Storage:** SQLite (procurement tracker only), JSON project files (all other apps) — no requirement to unify these
- **Fluid properties:** CoolProp only (open-source; REFPROP out of scope)
- **Numerics:** NumPy, SciPy (e.g. `scipy.optimize.brentq` for root-finding)
- **Plotting:** Matplotlib or Plotly
- **Reporting:** python-docx / reportlab (or equivalent) for calc package generation
- **Version control:** single monorepo recommended, given the shared `core` dependency

---

## 8. Open Questions for Dalton

Flag these rather than guessing:

- What's the first Process Hazards Analysis app? (Relief/venting sizing is the working assumption.)
- Is the cryogenic process simulation tool ready to be scoped, or still just "on the horizon"?
- Single monorepo confirmed, or does he want the suite split across per-category repos?
