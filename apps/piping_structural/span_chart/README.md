# Span Chart

**Status:** v0.3.0, available. Specs: `docs/app-specs/span-chart.md` (v1 base) and `docs/app-specs/span-chart-v2-load-cases.md` (load cases, governing).

## Purpose
Maximum support spacing for straight horizontal pipe, swept across NPS ½–24 or for a single size.

## Basis
- **Load cases (B31.3):** sustained W + P ≤ Sh (302.3.5). Occasional = sustained + one occasional load ≤ 1.33 Sh (302.3.6). Wind and seismic are never concurrent.
- **Environmental loads:** ASCE 7-16, each toggleable, with ASD factors per §2.4:
  - Wind: 0.6W
  - Seismic: 0.7E
  - Wind + snow: 0.75(0.6W) + 0.75S
  - Seismic + snow: 0.525E + 0.75S
  - Ice: 0.7D_i + 0.7W_i + S
- **Snow and ice weight:** can be treated as sustained or occasional.
- **Bending:** vector resultant of vertical and horizontal moments. Assumes lateral restraint (guides) at each support.
- **Pressure:** longitudinal stress P·D_o/(4t) is added to every stress case.
- **Deflection limit:** checked on pipe + contents only. Deflection including sustained snow/ice is also reported.
- **Beam models:**
  - Simply supported: wL²/8, 5wL⁴/384EI
  - Fixed-fixed: wL²/12, wL⁴/384EI
  - Continuous: wL²/10, with deflection from an N-span stiffness solve
  - Cantilever: wL²/2, wL⁴/8EI
- **Data sources:**
  - Sh: B31.3 Table A-1 (override available)
  - E: B31.3 App. C. Sh and E are from memory and **unverified**.
  - ASCE 7-16: transcribed from the licensed copy, with page cites.

## Outputs
- Governing span and governing case per size and end condition
- Span for every enabled case
- Both deflections
- Load breakdown per length
- Pressure stress
- Chart (marker = governing case), table, CSV
- Load details (q_z, p_f, t_d, F_p/W_p)
- JSON project file (v1 files still load)
- **Code tables & worked values:** an expander under each enabled load (wind/snow/ice/seismic) shows:
  - the ASCE 7-16 equations and source tables, with page cites and the row in use highlighted
  - the values used for the selected NPS
- **Pipe properties panel:** OD, wall, ID, metal and flow areas, projected D, I, Z, weights, and S_lp, filled in from the pipe being evaluated
- **Generate Tables (PDF):** pick any set of schedules and an NPS range to get a landscape PDF containing:
  - an inputs header
  - one table per end condition (NPS × schedule, span plus governing-case code)
  - data warnings
  - the generation timestamp on every page

## Conventions
- **Weight** uses the nominal wall. **Z and I** use the nominal wall × 0.875 (if mill tolerance is on) minus the corrosion allowance.
- **Contents** use the nominal ID.

## Known limitations
- No insulation weight and no point loads. Insulation thickness sets the projected diameter (OD + 2t) for wind, snow and ice only.
- No thermal expansion stress; that belongs in the Expansion Loop app.
- Snow is uniform on all spans. No §7.5.1 partial loading and no cornice loads between adjacent pipes.
- Not evaluated: K_zt speed-up (Fig. 26.8-1), seismic exemptions (§13.6.7.3), and the uplift combination (0.6D + 0.7D_i + 0.7W_i).
- Straight horizontal runs only. Single-wall pipe only; VJ is planned.

## Placeholders / TODO
- B31.3 data (Table A-1, App. C) and pipe dimensions are flagged unverified until checked (`docs/DATA-VERIFICATION.md`).
