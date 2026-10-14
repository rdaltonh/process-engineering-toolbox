# Corrugated Hose ΔP

**Status:** v0.1.0, available. Spec: `docs/app-specs/corrugated-hose-dp.md`.

## Purpose
Pressure drop of turbulent single-phase flow, liquid or gas, through one corrugated metal hose (annular or helical), with bends. The app reports the design point and plots ΔP against flow rate.

## Basis
- **Straight hose: two methods, computed side by side.**
  - **LSU (governs)**: J. R. Langley, K. L. Riley et al., *Flow Losses in Flexible Hose, Vol. I*, LSU / NASA-CR-62061, 1966.
    - Fanning f = α·Re^β, with α from (λ−σ)/ε and β from σε/λ².
    - α has separate water and air fits, and separate annular and helical fits.
  - **Hawthorne (cross-check, or fallback when depth and width are not entered)**: R. C. Hawthorne & H. C. von Helms, *Product Engineering*, 1963.
    - Each corrugation is treated as a sudden expansion.
    - k = 0.219·λ, C = [1 − (D/(D+2k))²]² per corrugation.
  - The spread between the two methods is shown as a rough indicator of uncertainty.
- **Bends: method depends on R/D.**

  | R/D | Method |
  |---|---|
  | ≥ 12.7 | LSU f/f₀ = 1 + 7.898·(D/R)^0.896, applied over the bent arc |
  | ≤ 5 | Hawthorne C_B chart (digitized), scaled linearly by θ/90 |
  | Between | Larger of the two |
  | < 0.7, or θ > 180° | Refused |

- **Gas** (Crane TP-410):
  - ΔP/P₁ ≤ 10%: inlet density.
  - ΔP/P₁ ≤ 40%: average density, with an acceleration term.
  - Above 40%: isenthalpic segment march, with ≤ 10% ΔP per segment and trapezoidal (mean) properties in each segment.
  - Mach 1 (choked flow) is refused.
- **Liquid:** inlet properties. If the outlet pressure falls below the saturation pressure, the result is flagged as cavitation and marked invalid.
- **Properties:** CoolProp, through `core/fluids/coolprop_wrapper.py`.

## Inputs
- **Fluid:** fluid name, inlet pressure (absolute), inlet temperature, mass flow.
- **Hose geometry:** corrugation type, minimum ID D, pitch λ, live length L.
  - Depth ε and inward-convolution width σ are optional. Entering them enables LSU.
- **Bends:** angle, centerline radius, position along the hose. Position is used only by the gas segment march.
- **Sweep range:** as a percentage of the design flow.

## Outputs
- ΔP, outlet pressure, velocity, Reynolds number.
- A per-method breakdown: straight run, each bend, acceleration.
- Fanning f, α/β/k/C/N, outlet Mach number, and the density basis used.
- ΔP vs flow plot, with untested, high-velocity and invalid regions marked.
- Sweep table with CSV export.
- Project file save and load.

## Limitations
- Both correlations come from 1960s air and water tests on ½–4½ in hose:
  - LSU: Re 6,000–580,000. For gas, V ≤ 140 ft/s; above that velocity the fit is likely unconservative.
  - Hawthorne: Re 2.4×10⁴ – 1.3×10⁶.
  - Other fluids use the water fit (liquids) or the air fit (gases), and the app warns.
- Accuracy is about ±20% for LSU (up to about 50% for 2½–3 in close-pitch hose) and −39% to +36% for Hawthorne. A manufacturer's ΔP curve, where one exists, takes precedence.
- Single hose only. No fittings, no two-phase flow.

## Unverified data
- The coefficients in `data/correlations.json` and the digitized `data/hawthorne_bend_cb.json` are flagged `verified: false` until spot-checked against the sources in `_inbox/`.
- Open item: the Hawthorne bend-angle exponent for θ < 90° is illegible in the scan. Linear scaling is used in the meantime, which is conservative.
