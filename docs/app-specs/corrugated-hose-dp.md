# Corrugated Hose Pressure Drop: App Spec (v1)

**Status:** rev 3 (2026-10-13). v0.1.0 built 2026-10-13 (114 tests passing). The only open item, the Vol. II data in Section 10, doesn't block the build.
**Category:** Fluid Analysis & Design
**Location:** `apps/fluid_analysis_design/corrugated_hose_dp/`

### Sources
All local copies are in `_inbox/`, which is gitignored.

| Tag | Reference | Local file |
|---|---|---|
| **[LSU]** | J. R. Langley, K. L. Riley (C. A. Whitehurst, B. S. Pressburg, PIs), *Flow Losses in Flexible Hose, Vol. I, Final Report*, Louisiana State Univ., Contract NAS 9-4630, Sept 1966. NASA-CR-62061, N68-22097, NTRS 19680012628. | `LSU_NAS9-4630_Final_Vol1_1966_Flow_Losses_Flexible_Hose.pdf` |
| **[LSU-QPR4]** | C. A. Whitehurst, *Flow Losses in Flexible Hose, Quarterly Progress Report No. 4*, NAS 9-4630, June 1966. NASA-CR-65433, NTRS 19660024205. Raw water data in App. III. | `LSU_NAS9-4630_QPR4_1966_Flow_Losses_Flexible_Hose.pdf` |
| **[H&vH]** | R. C. Hawthorne & H. C. von Helms, "Fluid expansion theory computes flow in corrugated hose," *Product Engineering*, June 10 1963, pp. 98–100. | `Hawthorne_1963_Flow_in_Corrugated_Hose.pdf` |
| Not yet obtained | [LSU] Vol. II (tabulated f data) and Vol. III (programs), which are not on NTRS. Also K. L. Riley, *Flow Losses in Flexible Hose*, PhD diss., LSU, 1967, 184 pp., doi:10.31390/gradschool_disstheses.1313, which likely holds the same data. | |

---

## 0. Decisions (Dalton, 2026-10-13)
- **Straight-hose method:** [LSU] is the primary method. [H&vH] is shown alongside as a cross-check. [H&vH] is the only method when σ is unknown (Section 3.2).
- **Bends:** hybrid. [LSU] for gentle sweeps, [H&vH] for tight bends. Between the two ranges the app warns and bounds the result (Section 3.3).
- **[H&vH] bend-angle exponent:** illegible in the scan. Until it is resolved the app uses **linear scaling (θ/90)**, which is conservative for θ < 90°, and labels it as an assumption.
- **Bend chart:** digitized from [H&vH] (Section 5), with `verified: false`.
- **σ:** the width of the convolution pointing toward the centerline (Section 2). Confirmed.
- **Sweep over part of the hose:** apply [LSU] Eq. 32 to the bent arc only (L_arc = R_B·θ), with straight-hose f elsewhere.
- **Gap regime (5 < R/D < 12.7):** take the larger of the two methods.
- **Compressibility (gas):** the Crane TP-410 density rule applies up to 40% ΔP/P₁. Above 40%, the app splits the hose into segments (Section 3.4).
- **Properties:** CoolProp, from inlet P, T and ṁ.
- **Scope v1:** a single hose, plus a ΔP vs flow plot.

## 1. Purpose
Estimate the pressure drop of turbulent liquid or gas flow through annular or helical corrugated metal hose, including bends. Report the design point and plot ΔP over a range of flows.

## 2. Geometry and nomenclature
Symbols follow [LSU] Fig. 1.

| Symbol | Meaning | Used by |
|---|---|---|
| D | **minimum** inside diameter (at the corrugation crest), labelled as such, not nominal | both |
| λ (= S in [H&vH]) | corrugation pitch | both |
| ε | corrugation depth (radial), measured on the fluid side from the minimum-ID line (D) to the bottom of the cavity | [LSU] |
| σ | axial width of the convolution pointing toward the centerline (the inward lobe that forms the minimum ID). This makes λ−σ the cavity opening at the ID. **Confirmed by Dalton 2026-10-13**, consistent with [LSU] Fig. 1 | [LSU] |
| L | developed (live) length | both |
| type | annular (close or open pitch) / helical | [LSU] |

[LSU] found that open pitch and close pitch need no separate fits; both are treated as "just annular".

## 3. Calculation

### 3.1 Common
- A = πD²/4, V = ṁ/(ρA), Re = ρVD/μ. Everything is based on D.
- ΔP = K·ρV²/2. With the Fanning friction factor f_F, K = 4·f_F·L/D.

### 3.2 Straight hose

**Primary method: [LSU] Eq. 27–35.** f_F = α·Re^β.

| | α |
|---|---|
| Liquid, annular (water fit, Eq. 29) | 0.01588·(λ−σ)/ε − 0.00215 |
| Liquid, helical (Eq. 30) | 0.02916·(λ−σ)/ε − 0.00886 |
| Gas, annular (air fit, Eq. 34) | 0.02202·(λ−σ)/ε − 0.00287 |
| Gas, helical (Eq. 35) | 0.04306·(λ−σ)/ε − 0.01318 |
| β, all (Eq. 31) | 0.2987·(σε/λ²) − 0.0313 |

- **Fluid mapping:** liquids other than water use the water fit, and gases other than air use the air fit. A warning names the fluid the fit came from.
- **Validity:**
  - Water: Re 6,000–380,000.
  - Air: Re 14,000–580,000 and **V ≤ 140 ft/s (42.7 m/s)**. Above that velocity, [LSU] measured f rising faster than the fit and gave no correlation. The app shows a strong warning that the result is unconservative.
  - Geometry: the Table I ranges (D 0.535–3.111 in). The parameter (λ−σ)/ε was fitted over about 0.26–0.79 for annular hose and 0.50–0.75 for helical hose; σε/λ² over about 0.32–0.83. Outside these ranges, warn.
  - If α ≤ 0, refuse: the fit is outside its domain.
- **Stated accuracy:** about ±20% per [LSU]. Its Table II shows average errors up to about 50% for 2½–3 in close-pitch hose.

**Cross-check: [H&vH] Eq. 4–5.** Always computed where it is valid.
- k = 0.219·λ
- C = [1 − (D/(D+2k))²]²
- K_straight = N·C, where N = L/λ
- Equivalent Fanning friction factor: f_F = C·D/(4λ)
- **Stated accuracy:** −39% to +36% against the paper's own 12 tests (Section 6.2).
- **Validity:**
  - Tested range: Re 2.4×10⁴ – 1.3×10⁶ and λ 0.125–0.375 in.
  - Re < 2000: use laminar flow (64/Re).
  - Re 2,000–24,000: warn.

**Display:**
- Both results are shown, with the spread between them (%).
- **[LSU] governs.**
- If σ or ε is not entered, [LSU] is skipped and [H&vH] governs, with a banner saying so.

**Laminar flow (Re < 2000):** f_F = 16/Re for both methods, with a warning. Neither source covers laminar or transitional flow below Re 6,000.

### 3.3 Bends

The two sources cover different bend regimes.

| Regime | Method | Notes |
|---|---|---|
| **Gentle sweep, R_B/D ≥ 12.7** | [LSU] Eq. 32: f/f₀ = 1 + 7.898·(D/R_B)^0.896 | f₀ is the straight-hose f. Applied over the **arc length L_arc = R_B·θ** (θ in radians). [LSU] tested whole-hose arcs about 10 ft long, with D/R_B from 0 to 0.0787. Applying it to only part of the hose is an interpretation, accepted by Dalton (Section 0). Independent of Re per [LSU]. |
| **Tight bend, r/D 0.7–5** | [H&vH] Eq. 6: ΔP_bend = C_B·(θ/90)·ρV²/2 | C_B comes from the digitized chart (Section 5). The arc length still counts as straight hose in N. Linear θ scaling is per Dalton's decision (Section 0). |
| **Gap, 5 < R_B/D < 12.7** | Compute both methods and take the **larger** | Warning: no source covers this regime. |
| r/D < 0.7 or θ > 180° | Refuse | Below the plotted [H&vH] curve, or outside the tested angles. |

Additional rules:
- Warn when the bend falls in a dashed region of the chart (r/D 0.7–1.0 or > 4.25).
- Bend loss is undefined for laminar flow: if Re < 2000, omit the bend loss and warn.

**Cross-check (test only, not shown in the app):** [LSU] whole-hose angle data and Table III (Section 6.1).

### 3.4 Properties and compressibility

**Fluid and inlet state**
- CoolProp fluid dropdown: water, N₂, He, Ar, H₂, O₂, Ne, air, CO₂, CH₄, plus free text.
- Inputs: P₁, T₁, and ṁ (or a volumetric flow, converted at inlet conditions).
- Phase check at the inlet:
  - Refuse a two-phase inlet.
  - Warn near saturation.

**Liquid**
- Properties are taken at the inlet.
- If P₂ < P_sat(T₁), the result is flagged invalid because of cavitation or flashing. [H&vH] excludes cavitation.

**Gas (and supercritical fluid), per Crane TP-410**

| ΔP/P₁ | Density treatment |
|---|---|
| ≤ 10% | Inlet density |
| 10–40% | Average density, iterated |
| > 40% | **Segment march**: ΔP_seg/P_seg ≤ 10%. Each segment uses the mean of its inlet and outlet properties (iterated, trapezoidal, second order) and re-evaluates Re and f. The state advances isenthalpically. *Build note: the first build used inlet-only properties, which changed the result by about 1% when the segment count doubled, failing acceptance criterion 5. Mean properties converge to within 0.001% at 20 segments.* |

**Acceleration (momentum) ΔP**
- Included in the segment march and in the 10–40% branch, and reported as its own line: ΔP_acc = G²(1/ρ₂ − 1/ρ₁).
- Rationale: [LSU] reduced its air friction factors with the isothermal momentum equation, which includes the acceleration term 2·ln(P₁/P₂) ([LSU] Eq. 26). Using their f without that term would be inconsistent. [H&vH] neglects it.

**Limits**
- Report the outlet Mach number.
- **Refuse at Mach ≥ 1** (choked).
- Warn when V > 140 ft/s (the [LSU] gas limit).

### 3.5 ΔP vs flow sweep
- Sweep ṁ from a minimum to a maximum (default 10–200% of design), 50 points, at a fixed inlet state.
- The plot shows:
  - [LSU] ΔP as a solid line and [H&vH] ΔP as a dashed line.
  - Shaded bands for laminar flow, untested Re, and V > 140 ft/s (gas).
  - Invalid points (cavitation, choking, two-phase) as markers labelled with the reason.
  - The design point.
- A secondary axis in hover shows the volumetric flow at inlet conditions.
- The sweep exports to CSV.

## 4. Inputs

| Group | Inputs |
|---|---|
| Fluid | CoolProp fluid; P₁; T₁; ṁ (or volumetric flow) |
| Hose | type (annular / helical); D (min ID); λ; ε; σ; L. ε and σ are optional; entering them enables [LSU] |
| Bends | 0..n rows: θ, centerline radius, position along the length. Position is used only by the gas segment march; the default is the outlet end, the worst case |
| Sweep | ṁ_min, ṁ_max |
| Display | US customary / SI |

## 5. Data: digitized [H&vH] 90° bend coefficient C_B vs r/D

- Digitized by Claude on 2026-10-13 from a 400 dpi render of p. 99, using gridline detection with skew correction.
- Checked visually with an overlay. Reading uncertainty is about ±0.005.
- Stored in `apps/fluid_analysis_design/corrugated_hose_dp/data/hawthorne_bend_cb.json` with `verified: false`.

| r/D | 0.7* | 0.8* | 0.9* | 1.0 | 1.25 | 1.5 | 1.75 | 2.0 | 2.25 | 2.5 | 2.75 | 3.0 | 3.25 | 3.5 | 3.75 | 4.0 | 4.25* | 4.5* | 5.0* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C_B | 0.455 | 0.428 | 0.405 | 0.381 | 0.328 | 0.284 | 0.246 | 0.217 | 0.187 | 0.164 | 0.144 | 0.126 | 0.111 | 0.099 | 0.089 | 0.082 | 0.076 | 0.074 | 0.074 |

\* Dashed (extrapolated) on the original.

The [LSU] coefficients and Table I come from clean typed source. They are transcribed with `verified: false` until Dalton spot-checks them.

## 6. Validation data (unit tests)

### 6.1 [LSU]
- **Table I geometry:** 24 hoses (close pitch, open pitch, helical), each with ID, λ, ε and σ in inches. Transcribed as fixtures.
- **Table III:** air, f/f₀ observed vs predicted at 60°, 120° and 180° for 6 hoses.
  - The app's Eq. 32 must reproduce the "predicted" column.
  - This requires R_B = L/θ with L = 10.0 ft. Claude confirmed that this gives 1.143 / 1.266 / 1.382 for the 1¼ in helical hose.
  - The observed values are reported for information only.
- **[LSU-QPR4] App. III raw water data:** 1.012 in close-pitch hose at 0°, 30° and 60° (GPM, V, Re, ΔP, f_F). The predicted f_F must be within ±25% of the median measured value in each Re decade. This is a sanity check rather than a tight tolerance, because of the measurement scatter.
- **Cross-check at Re = 10⁵, 1.012 in close-pitch hose:** [LSU] f_F = 0.0262 and [H&vH] f_F = 0.0274. Both are pinned to within 0.5%. For reference, the measured value in [LSU-QPR4] is about 0.0247.

### 6.2 [H&vH] test table (p. 100)
Transcribed from the scan. The table is internally consistent: C = f·S/D holds to within 0.5% on every row. Lengths are in inches.

| Nom | D in | L in | S in | N | Re | C test | f test | k test | C by Eq 5 | Eq 5 err |
|---|---|---|---|---|---|---|---|---|---|---|
| ¾ | 0.765 | 12 | 0.125 | 96 | 2.44e4 | 0.01225 | 0.0750 | 0.0225 | 0.01667 | +36% |
| 1 | 1.000 | 20.9 | 0.128 | 164 | 2.04e5 | 0.01350 | 0.1050 | 0.0318 | 0.01068 | −21% |
| 1 | 1.016 | 12 | 0.138 | 87 | 3.44e4 | 0.01015 | 0.0745 | 0.0275 | 0.01191 | +17% |
| 1¼ | 1.284 | 12 | 0.150 | 80 | 3.18e4 | 0.00927 | 0.0793 | 0.0330 | 0.00902 | −3% |
| 1½ | 1.500 | 20.3 | 0.163 | 124 | 4.02e5 | 0.00724 | 0.0666 | 0.0340 | 0.00789 | +9% |
| 1½ | 1.517 | 12 | 0.200 | 60 | 3.82e4 | 0.01050 | 0.0795 | 0.0420 | 0.01128 | +7% |
| 4 | 3.990 | 16 | 0.252 | 64 | 7.45e5 | 0.00376 | 0.0598 | 0.0640 | 0.00282 | −25% |
| 4 | 3.990 | 24 | 0.375 | 64 | 7.68e5 | 0.00548 | 0.0584 | 0.0785 | 0.00601 | +10% |
| 4 | 4.016 | 3 | 0.178 | 17 | 8.00e5 | 0.00198 | 0.0448 | 0.0460 | 0.00142 | −28% |
| 4 | 4.016 | 6 | 0.353 | 17 | 7.93e5 | 0.00454 | 0.0515 | 0.0710 | 0.00530 | +17% |
| 2 air | 2.000 | 36 | 0.212 | 170 | 1.18e5 | 0.00683 | 0.0647 | 0.0455 | 0.00753 | +10% |
| 4½ air | 4.460 | 2.5 | 0.167 | 15 | 1.32e6 | 0.00168 | 0.0448 | 0.0470 | 0.00102 | −39% |

## 7. Outputs
- **Design point:**
  - Total ΔP, broken down into straight-run, per-bend and acceleration components.
  - P₂, V, Re.
  - f_F from both methods, the spread between them, and which method governs.
  - α, β, k, C, N.
  - ρ and μ used. For gas: the density basis, segment count and outlet Mach.
- **Plot and sweep table** (Section 3.5), with CSV export.
- **Warnings banner** covering:
  - validity ranges (Re, geometry, V > 140 ft/s)
  - the bend-regime gap and the dashed chart region
  - the linear-θ assumption
  - fluid extrapolation (non-water / non-air)
  - cavitation, Mach and near-saturation
  - unverified data
  - both accuracy statements
- **Project file:** inputs, results, warnings and citations. Round-trip tested.

## 8. Acceptance criteria
1. The [H&vH] Eq. 5 US form (constant 9266) and the SI form agree within 5e-5. The paper rounds 2·32.174·144 = 9266.1 to 9266.
2. Section 6.2: the app's C matches the "C by Eq 5" column within 0.1%.
3. Section 6.1: Table III predicted values are reproduced within 0.5%, and the QPR4 sanity check and the cross-check pass.
4. A hand-calculated liquid case matches within 0.1% on each line item. The case: water, 1 in close-pitch hose, one 30° sweep at R_B = 4 ft, and one tight 90° bend at r/D = 2.
5. Gas cases at ΔP/P₁ of about 5%, 25% and 60% exercise all three density treatments. The segment march converges to within 0.5% when the segment count is doubled.
6. Laminar flow matches Fanning f = 16/Re exactly.
7. Each refusal path triggers: r/D < 0.7, θ > 180°, two-phase inlet, choked flow, α ≤ 0.
8. The app runs from the launcher and standalone. The README covers the basis, sources, limits, accuracy and unverified data.

**New core module:** `core/fluids/coolprop_wrapper.py` provides ρ, μ, phase, P_sat, h, a P–h flash and speed of sound. It becomes the roadmap's single CoolProp interface and will be reused by Line Sizing/JT.

## 9. Known limitations (v1)
- One hose at a time. No assemblies, fittings or end connections.
- No two-phase flow. Cryogenic liquids are accepted only when subcooled, with the near-saturation warning. [LSU] recommended a cryogenic study, but it was not done.
- Both correlations come from 1960s air and water data on ½–4½ in hose. Larger hose, braid effects, and fluids far from air and water are extrapolations.

## 10. Open questions for Dalton
1. ~~Definition of σ~~: resolved, inward convolution width (Section 2). The app's σ input tooltip shows the Fig. 1 sketch.
2. ~~Sweeps over part of the hose~~: resolved, arc only (Section 0).
3. ~~Gap regime~~: resolved, larger of the two (Section 0).
4. **[LSU] Vol. II / Riley dissertation.** If you can get either one (see Sources), the per-hose f vs Re data would replace the QPR4 sanity check with real per-hose tests.
