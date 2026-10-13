# Span Chart — App Spec (v1)

**Status:** v1 built 2026-10-12 per the decisions below. Data verification is pending (`docs/DATA-VERIFICATION.md`).
**Category:** Piping Structural
**Location:** `apps/piping_structural/span_chart/`
**Date:** 2026-10-12

---

## 0. Decisions (Dalton, 2026-10-12). These supersede conflicting text below.
- **Loads in v1:** pipe self-weight + contents only, with contents given by **specific gravity** (re: water at 60°F). Insulation, jacketing, extra uniform loads, and point loads are deferred. CoolProp contents lookup is deferred.
- **Thermal expansion/contraction:** reported (ΔL per 100 ft and over a user run length, installation → design T). It does not affect span.
- **E(T), thermal expansion:** ASME B31.3 Appendix C (C-6, C-1). Dalton holds the license. Values were entered from memory and are flagged **unverified** until checked.
- **Temperature range:** −40°F to +300°F, enforced.
- **Materials:** carbon steel (A106 B / A53 B), 304/304L, 316/316L, 5083-O.
- **Mill tolerance:** 12.5%, on by default.
- **Sizes:** NPS ½–24. Pipe dimensions transcribed from B36.10M/B36.19M (flagged unverified).
- **Allowable stress:** still a user input with a source field.

## 1. Purpose

Compute the maximum allowable support spacing for straight horizontal pipe under sustained (deadweight) load, for a single case or across a range of pipe sizes, and present the result as a chart and table. v1 covers bare and insulated single-wall pipe. Vacuum-jacketed pipe is deferred to v2.

## 2. Governing basis

- **Method:** classical beam theory. The span is the **lesser of** a stress-limited span and a deflection-limited span.
- **Code context:** consistent with ASME B31.3 sustained-load evaluation, where the sustained longitudinal stress from weight must not exceed the user-supplied allowable. The app does **not** reproduce or look up any ASME table, including B31.1 Table 121.5 and B31.3 Table A-1.
- The **allowable stress** and **deflection limit** are user inputs, each with a source/basis field that is recorded in the project file and shown in results.
- **Scope note shown in the app:** this is a support-spacing estimate for straight runs. It is not a substitute for flexibility/stress analysis of the full system (thermal, occasional loads, concentrated loads at fittings).

## 3. Calculation

For uniform load *w* (weight per length), span *L*, modulus *E(T)*, moment of inertia *I*, and section modulus *Z*:

| End condition | Max moment | Max deflection |
|---|---|---|
| Simply supported | wL²/8 | 5wL⁴ / (384EI) |
| Fixed-fixed | wL²/12 | wL⁴ / (384EI) |
| Continuous (industry convention) | wL²/10 | from an equal-span continuous-beam solution (see below) |
| Cantilever / overhang | wL²/2 | wL⁴ / (8EI) |

- **Stress-limited span:** solve M(L)/Z = S_allow, which gives L = √(k·Z·S_allow / w) for moment coefficient k.
- **Deflection-limited span:** solve δ(L) = δ_allow.
- **Governing span** = min(stress, deflection). The app reports which criterion governs.
- **Continuous-beam deflection:** v1 computes it with a small direct-stiffness beam solver (NumPy) for N equal spans (default 3, user-adjustable) rather than a tabulated coefficient. The end span governs. The wL²/10 moment is kept as the industry convention, and the solver's exact moment is also reported for comparison.
- **Unit tests:** cases are hand-verified against the closed-form formulas, and the stiffness solver is verified against the simply-supported/fixed closed forms.

### Sustained load *w* (per unit length)
- Pipe metal: ρ_metal × metal area, using the Materials Engine (or custom material) density.
- **Contents**, one of:
  - Empty
  - Water (hydrotest), via CoolProp at user T/P
  - Process fluid at user P/T via CoolProp (He, N₂, Ar, H₂, Ne, O₂, water, air), including saturated liquid
  - User-entered density
- **Insulation:** thickness + density (user-entered, with a source field). Optional jacketing weight per length.
- **Additional uniform load:** a user-entered extra per-length load (heat tracing, ice, etc.).
- Each component of w appears separately in the results so the breakdown is visible.

### Section properties
- From `core.piping.dimensions` (OD, nominal wall).
- **Wall used for Z and I:** nominal wall minus a user-entered corrosion/erosion allowance (default 0), with an optional mill-tolerance reduction (default 12.5%, toggle). Metal weight always uses the nominal wall. The chosen basis is recorded in the project file.

### Temperature
- E is evaluated at the design temperature via the Materials Engine. If T is outside the data range, the app errors, or extrapolates with a visible warning if the user opts in.
- The allowable stress entered by the user is understood to be at the design temperature, and the input label says so explicitly.
- Note shown for austenitic SS at cryogenic T: E is not monotonic. The app evaluates E at the actual T and never assumes a trend.

## 4. Inputs

| Group | Inputs |
|---|---|
| Pipe | Mode: single size or size sweep (NPS range); schedule; material (304 / 316L / 5083-O / custom) |
| Design condition | Design temperature; design pressure (only for contents density) |
| Allowables | S_allow at design T + source text (**required**, no default); deflection limit + basis (**required**). The UI shows common practice values as hints, not defaults |
| Section basis | Corrosion allowance; mill tolerance toggle |
| Loads | Contents option; insulation thickness/density; jacketing weight; extra uniform load |
| Beam model | End condition(s) to evaluate (multi-select); number of spans for continuous |
| Display | US customary / SI |

## 5. Outputs
- **Single case:** governing span, stress-limited span, deflection-limited span, governing criterion, the load breakdown, section properties used, E used (with citation), and the resulting stress and deflection at the governing span.
- **Size sweep:**
  - A Plotly chart of max span vs NPS, with one line per end condition, markers showing the governing criterion, and hover detail.
  - A sortable table.
  - CSV export.
- **Warnings banner:** placeholders, extrapolation, user-supplied (uncited) data, and the scope note.
- **Project file:** inputs, results, warnings, and citations (roadmap Section 3.3). The round-trip test covers it.

## 6. Acceptance criteria
1. The hand-calc test cases match within 0.1% for each end condition (stress- and deflection-governed cases both covered).
2. The stiffness solver reproduces the simply-supported and fixed closed forms within 0.1%.
3. Save → load round-trip is lossless, including units and warnings.
4. The app runs from the launcher and standalone.
5. With S_allow or the deflection limit missing, the app refuses to compute and says why.
6. No ASME table values appear in code or data.
7. The README covers purpose, basis, inputs/outputs, limitations, and placeholders.

## 7. Known limitations (v1)
- Straight horizontal runs only. No concentrated loads (valves, flanges), no bends, and no vertical risers beyond the cantilever case.
- Sustained weight only. No thermal, wind, or seismic loads.
- No VJ pipe (v2).
- Single-material pipe. No lined pipe.

## 8. Open questions for Dalton (resolved 2026-10-12, see Section 0)
1. **Concentrated loads:** add a single point load (valve/flange) at mid-span in v1, or defer?
2. **Mill tolerance default:** on (12.5%) or off for Z/I? The proposal is on, as the conservative choice.
3. **Size sweep range:** is NPS ½″–24″ enough, or do you need larger?
4. **Materials beyond the cryo set:** do you want A106 Gr B / A53 carbon steel in v1? NIST cryo data won't cover them, so E(T) would be a placeholder until you supply a source, or entered as a custom material.
5. **Pipe dimensions table:** OK for me to transcribe B36.10M/B36.19M OD and wall values (published dimensional data) for you to spot-check? Or do you have a source file you'd prefer?
