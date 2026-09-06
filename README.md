# AC Calculator for Stationeers

https://stndart.github.io/StationeersAC/

The optimizer maximizes cooling power at the requested load temperature
(`Q at target`, in kJ/tick), subject to locked settings and the modeled feed and heat
exchanger limits. Cascade search is bounded by each stage's full latent feed
capacity before sensible-heat losses. Temperature placement uses a discrete
search and heuristics, so the result is an approximate optimum. Unlocked chamber
counts and HX loop pressures use defaults; they are not unbounded search axes.
