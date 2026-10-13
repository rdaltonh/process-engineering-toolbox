# Contributing (humans and agents)

Read this before writing code. Full context lives in [ROADMAP.md](ROADMAP.md), Sections 2 and 6.

1. **Never fabricate safety-relevant values.** Allowables, thicknesses, span limits, ratings, and material properties must come from a verifiable source or from Dalton directly. Otherwise ship a placeholder (`"kind": "placeholder"`) with a warning. Values entered from memory are flagged `"verified": false` and surface as warnings until checked.
2. **Spec before build.** Write `docs/app-specs/<app>.md` (basis, inputs, outputs, limitations, open questions) and get it confirmed first.
3. **FOSS only.** No paid dependencies, no MATLAB, no REFPROP. CoolProp for fluids.
4. **Audit schemas on disk** before touching code that reads or writes them.
5. **Apps import only from `core`,** never from each other. Shared logic lives in `core` exactly once.
6. **Data lives in JSON, not code.** Material and pipe data go in `core/*/data/`.
7. **SI internally;** pint at the UI and file boundaries.
8. **Preserve validated engineering logic** when reimplementing. Flag proposed method changes for Dalton's review instead of changing them silently.
9. **Every app has a README** (purpose, basis, inputs/outputs, limitations, placeholders) and tests: hand-calc checks plus a lossless project-file round-trip.
