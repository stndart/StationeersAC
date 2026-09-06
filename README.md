# AC Calculator for Stationeers

https://stndart.github.io/StationeersAC/

The optimizer maximizes cooling power at the requested load temperature
(`Q at target`, in kJ/tick), subject to locked settings and the modeled feed and heat
exchanger limits. Cascade search is bounded by each stage's full latent feed
capacity before sensible-heat losses. Temperature placement uses a discrete
search and heuristics, so the result is an approximate optimum. Unlocked chamber
counts and HX loop pressures use defaults; they are not unbounded search axes.

Saturation pressure (the gas/liquid boundary at a given temperature) uses the
endpoints and tuned curves from [zgralewski's phase diagram](https://gralewski.github.io/stationeers-gas-phase-diagram-by-zgralewski.htm).
The data and `calcPressure` formula are pinned to
[source revision 83111b0](https://github.com/gralewski/gralewski.github.io/blob/83111b0fc1fcc623f077a99937710bf9198ff56b/stationeers-gas-phase-diagram-by-zgralewski.htm)
(2026-04-19 diagram). Both `cascade/gases.py` and `web/src/cascade/gases.js`
use its Kelvin/kPa endpoints and convexity parameters. These are tuned diagram
approximations, not an exact implementation of the game's phase engine.
The pressure at the maximum liquid temperature is a fixed endpoint; it is not
the saturation pressure at every temperature.

For normalized temperature `x = (T - Tmin) / (Tmax - Tmin)`, the curve is
`P = Pmin * (Pmax / Pmin) ** ((1-x)^2*x*a + (1-x)*x^2*b + x^2)`.
Pressure locks invert that same curve by bisection. Outside the liquid window,
endpoint tangents in log pressure preserve invalid lock values for freeze/critical
warnings; those extensions are diagnostic only, not valid phase predictions.
Old wiki boiling temperatures are retained as reference metadata, not curve anchors.
Thermal properties (heat capacity, latent heat, liquid volume) are unchanged.

`web/src/cascade/fixtures/phase_curve.json` contains endpoint and quarter-interval
samples evaluated from the upstream formula, independently of the solver.
Run `python -m unittest discover -s cascade/tests` and, in `web`, `npm test` and
`npm run build`. Regenerate solver parity fixtures with
`python -m cascade.dump_web_fixtures` after intentional model changes.

The standalone `calc_cascade.py`, `RESULTS.md`, and `cascade_numbers.json` are
legacy report artifacts using the previous interpolation, not the active optimizer.
