# Data Verification Checklist

Every value below was entered **from memory** (Claude, 2026-10-12) and is flagged `"verified": false`. The apps show an "Unverified data" warning until each item is checked against the licensed source and the flag is flipped.

**How to verify:** compare against your edition. Fix any wrong numbers in the JSON, then set `"verified": true` on that property (or at the top of the pipe file) and record the edition in its `citation`.

## 1. ASME B31.3 Appendix C: `core/materials/data/*.json`

### Table C-6: Modulus of elasticity, E (10⁶ psi)

| Material file | Group | −100°F | 70°F | 200°F | 300°F |
|---|---|---|---|---|---|
| `carbon_steel.json` | Carbon steels, C ≤ 0.3% | 30.2 | 29.5 | 28.8 | 28.3 |
| `ss304*.json`, `ss316*.json` (incl. dual cert) | Austenitic stainless | 29.0 | 28.3 | 27.6 | 27.0 |
| `al5083.json` | Aluminum alloys | 10.5 | 10.0 | 9.6 | 9.2 |

- [ ] Carbon steel E  - [ ] Austenitic E  - [ ] Aluminum E (also confirm 5083 sits in this group row)

### Table C-1: Total thermal expansion, in/100 ft from 70°F

| Material | −100°F | 0°F | 70°F | 100°F | 200°F | 300°F |
|---|---|---|---|---|---|---|
| Carbon steel | −1.21 | −0.51 | 0 | 0.23 | 0.99 | 1.82 |
| Austenitic SS | −1.86 | −0.77 | 0 | 0.34 | 1.46 | 2.61 |
| Aluminum | −2.36 | −1.02 | 0 | 0.46 | 2.00 | 3.61 |

- [ ] Carbon steel  - [ ] Austenitic SS  - [ ] Aluminum

The −100 and 0°F entries are my least certain values.

## 1b. ASME B31.3 Table A-1: basic allowable stress Sh (ksi): `allowable_stress` in each material file

| Material file | Spec | Min T to 100°F | 200°F | 300°F |
|---|---|---|---|---|
| `carbon_steel.json` | A106 B / A53 B | 20.0 | 20.0 | 20.0 |
| `ss304.json` | A312 TP304 | 20.0 | 20.0 | 20.0 |
| `ss304l.json` | A312 TP304L | 16.7 | 16.7 | 16.7 |
| `ss304_304l.json` | A312 TP304/304L dual cert | 20.0 | 20.0 | 20.0 |
| `ss316.json` | A312 TP316 | 20.0 | 20.0 | 20.0 |
| `ss316l.json` | A312 TP316L | 16.7 | 16.7 | 16.7 |
| `ss316_316l.json` | A312 TP316/316L dual cert | 20.0 | 20.0 | 20.0 |
| `al5083.json` | B241 5083-O | 10.7 to 150°F | (none) | (none) |

- [ ] Each row against your edition (note the edition in each file's `citation`)
- [ ] Dual-certified grades use the straight-grade allowable (20.0 ksi). Confirm the governing clause in your edition (B31.3 / ASME II) and record it in the `citation`
- [ ] The austenitic "HIGH_SH" note (302.3.2 Note 3 / reduced 1.33 factor). Is it applicable at these temperatures?

## 2. Densities (lb/in³)

| Material | Value | Notes |
|---|---|---|
| Carbon steel | 0.283 | |
| 304, 304L, 304/304L | 0.289 | |
| 316, 316L, 316/316L | 0.290 | |
| 5083-O | 0.096 | |

- [ ] Confirm each and name a source (e.g. ASME II-D Table PRD, or mill/handbook data)

## 3. Service-temperature notes (warnings only, not limits enforced in calcs)

- [ ] Carbon steel below −20°F: B31.3 impact-test/MDMT note (`carbon_steel.json` → `service_notes`)
- [ ] 5083 above 150°F: B31.3 restriction on Mg > 3% aluminum alloys (`al5083.json` → `service_notes`)

## 4. Pipe dimensions (ASME B36.10M / B36.19M): `core/piping/data/pipe_dimensions.json`

There are 21 sizes (NPS ½–24) across 17 schedules. Already cross-checked indirectly: the computed I and Z for 2" and 4" Sch 40 match published handbook values (tests pin them).

Spot-check at least:
- [ ] Sch 40 / STD across all sizes (STD = 0.375″ for NPS ≥ 12)
- [ ] Sch 80 / XS across all sizes (XS = 0.500″ for NPS ≥ 10)
- [ ] Sch 160 and XXS (3½″ intentionally omitted from both)
- [ ] 5S / 10S / 40S / 80S stainless
- [ ] Sch 10–30, 60, 100–140 (NPS 8+ mostly; Sch 120 starts at NPS 4)

Once everything is verified, set `"verified": true` at the top of the file.

## 5. ASCE 7-16: `core/loads/data/asce7_16.json`

These values were **transcribed directly from your licensed copy** (not from memory) and marked `verified: true`, with printed page numbers in each entry. A second look is still worthwhile:
- [ ] Table 26.11-1 α, z_g (p. 269) · Table 26.6-1 K_d round = 1.0 (p. 266) · G = 0.85 (p. 269)
- [ ] Fig. 29.4-1 C_f round, h/D = 25 column (p. 325)
- [ ] Table 7.3-1 C_e, Table 7.3-2 C_t = 1.2 (p. 58) · Eq. 7.7-1 γ (p. 59) · §7.13.3 / Fig. 7.13-2 (p. 64)
- [ ] Table 1.5-2 I_s, I_i (p. 5) · §10.4 ice (pp. 70–71)
- [ ] Table 13.6-1 piping a_p / R_p (p. 129) · Eqs. 13.3-1 to 13.3-3, §13.3.1.2 (p. 123)

## 6. Stainless tube: `core/piping/data/tube_dimensions.json`

Tube OD and wall are the ordered dimensions, so they're exact by definition. Two things are from memory and need checking:
- [ ] **OD/wall availability** (common commercial combinations):

| OD | Walls offered (in) |
|---|---|
| 1/4, 3/8 | 0.020, 0.028, 0.035, 0.049, 0.065 |
| 1/2 | 0.028, 0.035, 0.049, 0.065, 0.083 |
| 5/8 | 0.035, 0.049, 0.065, 0.083, 0.095 |
| 3/4 | 0.035 to 0.109 |
| 7/8 | 0.049 to 0.109 |
| 1 | 0.049 to 0.120 |
| 1-1/4, 1-1/2, 2 | 0.065 to 0.120 |

- [ ] **Wall tolerance 10%** (ASTM A269), applied when mill tolerance is on. Pipe stays at 12.5%.
- [ ] **Sh for A269 tube** assumed equal to the A312 pipe value of the same grade (Table A-1)
