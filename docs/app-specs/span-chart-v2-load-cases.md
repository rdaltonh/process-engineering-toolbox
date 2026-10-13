# Span Chart v2: B31.3 Load Cases + ASCE 7-16 Environmental Loads

**Status:** Built 2026-10-12 (v0.2.0) per Section 0 decisions. ASCE 7-16 values were transcribed from Dalton's copy.
**Date:** 2026-10-12
**Supersedes:** `span-chart.md` Sections 0, 3, and 4 wherever they conflict. Everything not mentioned here (beam models, mill tolerance, dimensions, UI shell, project files) carries over unchanged.

---

## 0. Final decisions (Dalton, 2026-10-12). These supersede Sections 3 and 9.

- **K_d** = 1.0 (round, Table 26.6-1).
- **Occasional bending:** vector resultant, M = √(M_v² + M_h²), so w_eff = √(w_v² + w_h²) (same beam model in both planes). This assumes supports restrain the pipe laterally at the same locations as vertically (guides). The app states the assumption.
- **ASD combinations** follow ASCE 7-16 §2.4.1/2.4.3/2.4.5 (pp. 8–9), including the snow-concurrent cases.
- **Deflection** is checked on pipe + contents only. Deflection with sustained snow/ice is reported alongside it, not checked.
- **Snow partial loading (§7.5.1):** not applied. Snow is uniform on all spans, as in typical piping practice. The app notes that selecting "simply supported" bounds partial-loading effects.
- **Ice (Ch. 10)** is added as an option with the same sustained/occasional toggle as snow.

### Final case set (each case appears only when its loads are enabled)

| Case | ASCE 7-16 ASD basis | w_v | w_h | Limit |
|---|---|---|---|---|
| SUS | Comb. 1 (+0.7D_i per §2.4.3-4) | W (+ S if snow is sustained) (+ 0.7D_i if ice is sustained) | none | Sh |
| OCC-SNOW (snow occasional) | Comb. 3 | W + S | none | 1.33 Sh |
| OCC-WIND | Comb. 5 | W_sus | 0.6·W_wind | 1.33 Sh |
| OCC-WIND+SNOW | Comb. 6 | W_sus + 0.75·S* | 0.75·0.6·W_wind | 1.33 Sh |
| OCC-SEISMIC | Comb. 8 | W_sus + 0.7·E_v | 0.7·E_h | 1.33 Sh |
| OCC-SEISMIC+SNOW | Comb. 9 | W_sus + 0.525·E_v + 0.75·S* | 0.525·E_h | 1.33 Sh |
| OCC-ICE | Comb. 3 per §2.4.3-2 | W_sus + 0.7·D_i* + S* | 0.7·W_i | 1.33 Sh |
| DEFLECTION | none | W (pipe + contents) | none | δ_allow |

W_sus is the SUS vertical load. Items marked * are added only when that load is occasional; if it's sustained, it's already in W_sus at its sustained factor. Comb. 7 (0.6D + 0.7D_i + 0.7W_i) is an uplift case and doesn't govern a gravity span. W and seismic never combine.

**Ice load (§10.4, pp. 69–71):**
- t_d = t·I_i·f_z·K_zt^0.35, where f_z = (z/33)^0.10 ≤ 1.4 and I_i comes from Table 1.5-2 (0.80 / 1.00 / 1.15 / 1.25).
- D_i = 56 pcf × π·t_d(D_c + t_d), with D_c = D_proj.
- Wind on ice: concurrent wind speed V_c (Figs. 10.4-2 to 10.4-6), projected diameter D_proj + 2t_d, C_f = 1.2 (§10.5.1), I_w = 1.0, and the same K_z / K_zt / K_d / G as wind.
- Inputs: nominal ice thickness t and V_c (from the maps).

**Note on the 1.33 factor:** ASCE 7 §2.4.1 bars allowable-stress increases unless they are justified by rate or duration of load. B31.3 ¶302.3.6's 1.33 Sh for occasional loads is that kind of material-code, duration-based provision. Combining ASCE ASD loads with B31.3's 1.33 is common practice, and the app cites both.

## 0b. Tube option (Dalton, 2026-10-13)
- A Pipe/Tube toggle. Tube is stainless only (304, 304L, 316, 316L, and the dual-cert grades), ASTM A269.
- ODs: 1/4, 3/8, 1/2, 5/8, 3/4, 7/8, 1, 1-1/4, 1-1/2, 2. Walls: common commercial combinations up to 0.120 in.
- Tube wall tolerance is 10% (A269) when mill tolerance is on.
- All load cases and outputs are the same as for pipe.

## 1. Changes from v1

| Change | Detail |
|---|---|
| **Removed** | Thermal ΔL report, installation temperature, and run length inputs. The thermal-expansion data stays in the Materials Engine for the future Expansion Loop app |
| **Added** | Design pressure, entering the sustained stress through the longitudinal pressure stress |
| **Added** | Wind, snow, and seismic loads per **ASCE 7-16**, **each individually toggleable** |
| **Added** | B31.3 load cases: sustained ≤ Sh, occasional ≤ 1.33 Sh |
| **Changed** | Sh comes from B31.3 Table A-1 data (entered from memory, flagged unverified) with a manual override. The free-entry field remains as an override |
| **Changed** | Materials split into 304, 304L, 316, and 316L, because their A-1 allowables differ |

## 2. Research summary: how B31.3 load cases are normally applied

| Category | B31.3 ¶ | Typical combination | Limit |
|---|---|---|---|
| Sustained (SUS) | 302.3.5 | W + P (weight of pipe + contents + other sustained loads, plus pressure) | S_L ≤ Sh |
| Occasional (OCC) | 302.3.6 | SUS + wind **or** SUS + earthquake (also PSV reaction, etc.) | S_L + S_occ ≤ 1.33 Sh |
| Expansion (EXP) | 302.3.5(d) | Operating − sustained (thermal displacement range) | S_E ≤ S_A |

Key points:
- **Wind and earthquake are not considered concurrent** (302.3.6). They are separate occasional cases.
- **Expansion stress** (S_A = f(1.25Sc + 0.25Sh), or the liberal form using Sh − S_L) depends on system geometry and displacements, **not on support spacing**. It is out of scope for a span chart, which agrees with your call to drop thermal. It belongs in the Expansion Loop app.
- **Snow/ice** sits under B31.3's weight effects (live load) per ¶301.6, which suggests sustained. Many projects treat it as occasional instead. **Your decision: a user toggle, default sustained.**
- **ASCE 7 wind and seismic** (7-16 onward) are **strength-level**, while B31.3 is allowable-stress based. Common practice applies the ASCE 7 §2.4 ASD factors: **0.6W** and **0.7E**. **Your decision: apply them.**
- **Sustained stress form (B31.3-2016 and later, ¶320.2):** S_L = √((|S_a| + S_b)² + (2S_t)²). For straight pipe with no torsion, this reduces to S_L = S_a + S_b. Here S_a includes the longitudinal pressure stress P·D_o/(4t), and S_b = M/Z. The 1.33 factor carries a caveat: it must be reduced if Sh exceeds 2/3 of yield (302.3.2 Note 3). That applies to some austenitic A-1 values, so the app flags it (see Section 7).

## 3. Load cases evaluated

The span is the minimum over every **enabled** case, plus the deflection check:

| Case | Vertical load w_v | Horizontal load w_h | Stress limit |
|---|---|---|---|
| **SUS** | pipe + contents (+ snow if toggle = sustained) | none | Sh |
| **OCC-SNOW** (only if toggle = occasional) | pipe + contents + snow | none | 1.33 Sh |
| **OCC-WIND** | SUS w_v | 0.6 × wind | 1.33 Sh |
| **OCC-SEISMIC** | SUS w_v ± 0.7 × vertical seismic | 0.7 × horizontal seismic | 1.33 Sh |
| **DEFLECTION** | pipe + contents only | none | δ ≤ δ_allow |

**Stress in occasional cases** follows the 302.3.6 scalar sum: S_occ,total = S_lp + k·w_v·L²/Z + k·w_h·L²/Z ≤ 1.33 Sh. This is conservative versus the vector resultant √(w_v² + w_h²), since the two bending planes are orthogonal. The vector option is listed as Open Question 3.

**Solving for span:** L = √(k·Z·(S_limit − S_lp) / w_eff). If S_lp ≥ S_limit, the pipe fails on pressure alone and the app reports that.

Combining snow and wind in one case (ASCE 7 combination D + 0.75(0.6W) + 0.75S) is **not** included by default. See Open Question 4.

## 4. ASCE 7-16 load calculations (per unit length of pipe)

Every equation and table value below was **read from Dalton's licensed ASCE 7-16 PDF** (page numbers are printed pages). It goes into `core/loads/data/asce7_16.json` with page citations and `verified: true` (transcribed from source, not memory). Each value can be overridden in the UI.

### 4.1 Wind (Ch. 26 & 29.4, other structures)
- **Velocity pressure:** q_z = 0.00256·K_z·K_zt·K_d·K_e·V² (psf, V in mph), Eq. 26.10-1, p. 268. In 7-16, K_d **is** inside q_z.
- **K_z** (Table 26.10-1 note 1, p. 268):
  - 15 ft ≤ z ≤ z_g: K_z = 2.01(z/z_g)^(2/α)
  - z < 15 ft: K_z = 2.01(15/z_g)^(2/α)
  - α and z_g from Table 26.11-1 (p. 269): B = 7.0 / 1200 ft, C = 9.5 / 900 ft, D = 11.5 / 700 ft. Exposure definitions: §26.7.3.
- **K_e** (Table 26.9-1, p. 268): = e^(−0.0000362·z_g), with z_g the ground elevation in ft. 1.0 is permitted (default).
- **K_zt:** default 1.0 (§26.8.2, p. 268). Fig. 26.8-1 speed-up is not implemented; use the override.
- **K_d** (Table 26.6-1, p. 266): "Chimneys, tanks, and similar structures, Round" = **1.0**, paired with the Fig. 29.4-1 C_f below. Footnote: 0.95 is permitted for nonaxisymmetric structural systems. *(Your margin note in the PDF says 0.85, which is the open-structure value. See Open Question 1.)*
- **G** = 0.85 (§26.11.1, p. 269, rigid structure).
- **Force:** F = q_z·G·C_f·A_f (Eq. 29.4-1, p. 322), so w_wind = q_z·G·C_f·D_proj.
- **C_f** (Fig. 29.4-1, p. 325, round). A pipe run has h/D ≫ 25, so the h/D = 25 column applies:
  - D√q_z > 2.5 (D in ft, q_z in psf): moderately smooth 0.7, rough (D′/D = 0.02) 0.9, very rough (D′/D = 0.08) 1.2
  - D√q_z ≤ 2.5: 1.2
- **ASD:** w_h = 0.6·w_wind.
- **Inputs:** V (Fig. 26.5-1, risk category map), exposure B/C/D, centerline height z, ground elevation (for K_e, optional), K_zt, surface roughness, D_proj (defaults to OD; override for insulation).

### 4.2 Snow (Ch. 7, §7.13.3 pipes)
- **Flat-roof snow load:** p_f = 0.7·C_e·C_t·I_s·p_g (Eq. 7.3-1, p. 51).
- **C_e** (Table 7.3-1, p. 58), fully exposed / partially exposed / sheltered: B 0.9/1.0/1.2, C 0.9/1.0/1.1, D 0.8/0.9/1.0. Default: fully exposed, matched to the wind exposure.
- **C_t** (Table 7.3-2, p. 58): unheated and open-air structures = **1.2**. §7.13 also requires C_t = 1.2 for open-frame equipment structures.
- **I_s** (Table 1.5-2, p. 5): risk category I 0.80, II 1.00, III 1.10, IV 1.20.
- **Snow density:** γ = 0.13·p_g + 14 ≤ 30 pcf (Eq. 7.7-1, p. 59).
- **Load on an individual pipe** (§7.13.3, Fig. 7.13-2a/b, p. 64). D = pipe OD + 2 × insulation; angle of repose 70°.
  - **D ≤ 0.73·p_f/γ:** triangular load, height 1.37D, so w_snow = ½·D·1.37D·γ = 0.685·γ·D².
  - **D > 0.73·p_f/γ:** trapezoidal load, height h = p_f/γ with 70° sides, so w_snow = γ·h·(D − h/tan 70°). This reduces to the triangle at the D = 0.73·p_f/γ transition (continuity checked).
  - **Exemption:** "Snow loads on pipes are not required to be considered if the wintertime external surface temperature of the pipe is greater than 45°F." This is an input. For cryogenic or chilled lines it never applies.
  - **Cornice loads** between closely spaced adjacent pipes (Fig. 7.13-3) are out of scope for a single-pipe span chart. The app notes this.
- **Inputs:** p_g (Fig. 7.2-1 or a site value), exposure condition, risk category, the "wintertime surface > 45°F" checkbox, and the sustained/occasional toggle.

### 4.3 Seismic (Ch. 13, §13.3.1 and §13.6.7)
- **Horizontal force:** F_p = 0.4·a_p·S_DS·W_p·(1 + 2z/h) / (R_p/I_p) (Eq. 13.3-1, p. 123).
  - Bounds: 0.3·S_DS·I_p·W_p ≤ F_p ≤ 1.6·S_DS·I_p·W_p (Eqs. 13.3-2 and 13.3-3).
  - z/h ≤ 1.0. z = 0 at or below grade.
- **Vertical:** concurrent ±0.2·S_DS·W_p (§13.3.1.2, p. 123).
- **Table 13.6-1, Distribution Systems** (p. 129), a_p / R_p:

  | Piping type | a_p | R_p |
  |---|---|---|
  | ASME B31, welded or brazed (default) | 2½ | 12 |
  | ASME B31, threaded/bonded/grooved, or limited-deformability material | 2½ | 6 |
  | Not per B31, welded or brazed | 2½ | 9 |
  | Not per B31, threaded etc. | 2½ | 4½ |
  | Low-deformability (cast iron, glass, nonductile plastics) | 2½ | 3 |

- **I_p:** 1.0 or 1.5 (§13.1.3).
- **ASD:** horizontal w_h = 0.7·F_p/L. Vertical w_v adds 0.7 × 0.2·S_DS·w (downward governs).
- **Inputs:** S_DS, I_p, piping type (selects a_p and R_p), z and h (or z/h).
- **Note:** §13.6.7 exempts some piping from seismic design (trapezes or hangers ≤ 12 in., size limits by SDC). The app doesn't evaluate exemptions; the user simply toggles seismic off.

## 5. Allowable stress: B31.3 Table A-1 (from memory, unverified)

Sh (ksi) as a function of temperature, with linear interpolation in the Materials Engine. The engine already refuses temperatures outside the data range.

| Material | Spec | Min T to 100°F | 200°F | 300°F | Notes |
|---|---|---|---|---|---|
| Carbon steel | A106 B / A53 B | 20.0 | 20.0 | 20.0 | |
| 304 | A312 TP304 | 20.0 | 20.0 | 20.0 | |
| 304L | A312 TP304L | 16.7 | 16.7 | 16.7 | |
| 316 | A312 TP316 | 20.0 | 20.0 | 20.0 | |
| 316L | A312 TP316L | 16.7 | 16.7 | 16.7 | |
| 5083-O | B241 | 10.7 | (none) | (none) | Data to 150°F only, so higher temperatures are refused |

- ~~Dual-certified modeled as L-grade~~ **Revised 2026-10-12 (Dalton):** dual-certified 304/304L and 316/316L are separate materials using the straight-grade (higher) Sh, because the pipe meets both grades' requirements. A standing note says to confirm this against the MTR.
- The Sh override field replaces the table value and requires a source note.

## 6. Inputs (new or changed)

| Group | Inputs |
|---|---|
| Design | Design temperature (−40 to 300°F); **design pressure (psig)** |
| Allowable | Sh (auto from A-1, shown with citation); override toggle + value + source |
| Load toggles | ☐ Wind ☐ Snow (+ sustained/occasional selector) ☐ Seismic, each revealing its own input panel |
| Wind | V, exposure, z, ground elevation (K_e), K_zt, K_d, G, surface roughness → C_f (auto or override), D_proj |
| Snow | p_g, exposure condition → C_e, C_t (1.2), risk category → I_s, wintertime surface > 45°F checkbox, D_proj (shared with wind) |
| Seismic | S_DS, I_p, z, h, piping type → a_p and R_p (Table 13.6-1) |
| ASD factors | 0.6 (wind) and 0.7 (seismic), shown read-only with their basis |

## 7. Outputs (new or changed)
- **Per size and end condition:** the governing span and **which case governs** (SUS / OCC-WIND / OCC-SEISMIC / OCC-SNOW / DEFLECTION), plus the stress-limited span for each enabled case.
- **Load breakdown per length:** pipe, contents, snow, wind (strength and ASD), seismic horizontal/vertical (strength and ASD).
- **Stress breakdown at the governing span:** S_lp, S_b,sus, S_b,occ, and the utilization against each limit.
- **Chart:** the marker shape encodes the governing case.
- **Warnings:**
  - all from-memory data (A-1, App. C, ASCE 7 coefficients, pipe dimensions);
  - snow exemption applied (surface > 45°F);
  - cornice loads between adjacent pipes not evaluated;
  - S_lp ≥ limit;
  - the 302.3.2 Note 3 flag for austenitic Sh near or above 2/3 yield. v1 only warns here, since yield isn't in the engine yet.

## 8. Acceptance criteria
1. Hand-calc tests for each case: SUS with pressure, OCC-WIND, OCC-SEISMIC (including the F_p bounds), and snow as both sustained and occasional.
2. Each toggle on/off changes only its own case.
3. Wind and seismic are never combined in one case.
4. The project file round-trips with all new inputs. Old v1 project files load: the schema stays at 1.0, and v1 inputs are app-level, so the app maps them by ignoring removed thermal fields and defaulting new ones.
5. All existing tests still pass, with the thermal tests moved to the materials tests.

## 9. Open questions
1. **K_d for pipes:** 1.0 (Table 26.6-1 round "chimneys, tanks, and similar", consistent with using Fig. 29.4-1 C_f; proposed default), or 0.85 per your margin note (the open-structure value)?
2. **Occasional stress combination:** scalar sum (default, conservative, follows 302.3.6 wording), or vector resultant of vertical and horizontal bending?
3. **Snow + wind concurrency:** add an optional ASCE 7-16 §2.4 combination case, SUS + 0.75(0.6W) + 0.75S?
4. **Deflection check:** pipe + contents only (proposed), or include snow when it's sustained?
5. **Snow partial loading on continuous spans** (§7.5.1, p. 54: full/half snow patterns on continuous beams): the beam solver can do this. Include it for the continuous end condition, or treat it as uniform?
6. **Ice loads** (ASCE 7 Ch. 10): defer?

## 10. Sources consulted
- B31.3 load-case practice (secondary): [learning.malyomar.com](https://learning.malyomar.com/asme-b31-3-piping-load-cases-sustained-occasional-expansion/), [SST CAEPIPE supplement](https://www.sstusa.com/downloads/ReadMeSupplement_515.pdf), [CAESAR II User's Guide](https://docs.hexagonppm.com/r/en-US/CAESAR-II-Users-Guide/Version-12/335344), [epcland CAESAR II load cases](https://epcland.com/caesar-ii-load-cases/)
- Sustained stress equation, ¶320.2: [Engineers Edge calculator](https://engineersedge.com/calculators/pipe_stress_due_to_sustained_loads__16136.htm), [SST supplement v652](https://www.sstusa.com/downloads/ReadmeSupplement_v652.pdf)
- ASCE 7-22 wind (K_d moved out of q_z): [SPRI 2023 ASCE 7 presentation](https://www.spri.org/wp-content/uploads/2023/10/2-2023-WDS-ASCE-7_Chamberlain.pdf), [Eng-Tips on pipes as other structures](https://eng-tips.com/viewthread.cfm?qid=466468)
- ASCE 7-22 seismic Ch. 13 (H_f, R_μ, C_AR, R_po; bounds unchanged): [HCAI OPM-0747](https://hcai.ca.gov/document/OPM-0747), [Simpson Strong-Tie SE blog](https://seblog.strongtie.com/2026/05/asce-7-22-shakes-things-up-changes-to-seismic-calculations-for-anchorage-of-equipment/), [NIBS NEHRP Ch. 8](https://nibs.org/files/pdfs/20211209_2020NEHRP-training-materials_CH-8_Nonstructural-Components-Reduced.pdf)
- Snow on pipes/OFES: [ASCE "Snow Loads on Non-Building Structures"](https://ascelibrary.com/doi/10.1061/9780784412367.129), [Eng-Tips on Fig. 7.13-2](https://www.eng-tips.com/viewthread.cfm?qid=478332)

- **ASCE 7-16 (primary):** Dalton's licensed copy, `_inbox/ASCE_7_16_MINIMUM_DESIGN_LOADS_2017.pdf` (local only, gitignored), pp. 5, 51, 58, 59, 64, 123, 129, 266, 268, 269, 322, 325.

B31.3 values (A-1, App. C) remain from memory and unverified until checked against your licensed B31.3.
