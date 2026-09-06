"""Gas table and tuned saturation-pressure curves."""

from __future__ import annotations

import math
from dataclasses import dataclass

from cascade.constants import LIQUID_FEED_L_PER_TICK


@dataclass(frozen=True)
class Gas:
    name: str
    symbol: str
    shc: float | None  # J/(K mol)
    latent: float | None  # J/mol
    t_freeze: float | None  # K
    t_crit: float | None  # K
    p_min_cond: float | None  # kPa at freeze
    p_crit: float | None  # kPa at t_crit
    v_liq: float | None  # L/mol
    mw: float | None  # g/mol
    boil_100kpa: float | None  # K
    notes: str
    convexity_start: float | None = None
    convexity_end: float | None = None

    def _exponent(self, t: float) -> float:
        # Endpoint tangents outside [0, 1] preserve invalid-lock diagnostics.
        a, b = self.convexity_start, self.convexity_end
        if a is None or b is None:
            raise ValueError(f"{self.symbol}: no saturation curve")
        if t < 0:
            return a * t
        if t > 1:
            return 1 + (2 - b) * (t - 1)
        return (1 - t)**2 * t * a + (1 - t) * t**2 * b + t**2

    def p_sat(self, t: float) -> float:
        """Tuned diagram curve: K -> kPa. See README for source and limits."""
        if self.t_freeze is None or self.t_crit is None or self.p_min_cond is None or self.p_crit is None:
            raise ValueError(f"{self.symbol}: no saturation curve")
        x = (t - self.t_freeze) / (self.t_crit - self.t_freeze)
        return self.p_min_cond * (self.p_crit / self.p_min_cond)**self._exponent(x)

    def t_sat(self, p: float) -> float:
        """Invert the monotonic curve; retain out-of-window pressure locks."""
        if self.convexity_start is None or self.convexity_end is None:
            raise ValueError(f"{self.symbol}: no saturation curve")
        exponent = math.log(max(p, 1e-9) / self.p_min_cond) / math.log(self.p_crit / self.p_min_cond)
        if exponent < 0:
            x = exponent / self.convexity_start
        elif exponent > 1:
            x = 1 + (exponent - 1) / (2 - self.convexity_end)
        else:
            lo, hi = 0.0, 1.0
            for _ in range(52):
                mid = (lo + hi) / 2
                if self._exponent(mid) < exponent:
                    lo = mid
                else:
                    hi = mid
            x = (lo + hi) / 2
        return self.t_freeze + x * (self.t_crit - self.t_freeze)

    def mol_per_tick_feed(self) -> float:
        if not self.v_liq:
            raise ValueError(f"{self.symbol}: missing liquid molar volume")
        return LIQUID_FEED_L_PER_TICK / self.v_liq

    def can_refrigerate(self) -> bool:
        return (
            self.latent is not None
            and self.v_liq is not None
            and self.t_freeze is not None
            and self.t_crit is not None
            and self.p_min_cond is not None
            and self.p_crit is not None
        )


GASES: dict[str, Gas] = {
    "N2": Gas(
        "Nitrogen",
        "N2",
        20.6,
        500,
        40.0,
        190.0,
        6.3,
        6000.0,
        0.0348,
        28.02,
        75.0,
        "Phase curve: zgralewski diagram (2026-04-19).",
        2.0,
        1.3655,
    ),
    "O2": Gas(
        "Oxygen",
        "O2",
        21.1,
        800,
        56.0,
        162.0,
        6.3,
        6000.0,
        0.03,
        15.99,
        90.0,
        "Phase curve: zgralewski diagram (2026-04-19).",
        1.6053,
        1.3421,
    ),
    "CH4": Gas(
        "Methane / Volatiles",
        "CH4",
        20.4,
        1000,
        81.0,
        195.0,
        6.3,
        6000.0,
        0.04,
        16.04,
        112.0,
        "Phase curve: zgralewski diagram (2026-04-19).",
        1.5126,
        1.2842,
    ),
    "H2": Gas(
        "Hydrogen",
        "H2",
        20.4,
        200,
        15.0,
        70.0,
        6.3,
        6000.0,
        0.028,
        2.0,
        28.11,
        "Phase curve: zgralewski diagram (2026-04-19).",
        2.0,
        1.3331,
    ),
    "HE": Gas(
        "Helium",
        "He",
        20.8,
        None,
        None,
        None,
        None,
        None,
        None,
        4.0,
        None,
        "Wiki Module:Gas/data. Inert; never freezes or condenses (L=0, A=B=0). Best coupling / Stirling gas (gamma 5/3, SHC 20.8, MW 4).",
    ),
    "X": Gas(
        "Pollutant",
        "X",
        24.8,
        2000,
        173.0,
        434.0,
        1800.0,
        6000.0,
        0.04,
        64.0,
        None,
        "Phase curve: zgralewski diagram (2026-04-19).",
        1.5508,
        1.3219,
    ),
    "CO2": Gas(
        "Carbon Dioxide",
        "CO2",
        28.2,
        600,
        218.0,
        266.0,
        517.0,
        6000.0,
        0.04,
        44.01,
        None,
        "Phase curve: zgralewski diagram (2026-04-19).",
        1.0709,
        1.0793,
    ),
    "N2O": Gas(
        "Nitrous Oxide",
        "N2O",
        37.2,
        4000,
        251.0,
        431.0,
        800.0,
        2000.0,
        0.026,
        46.0,
        None,
        "Phase curve: zgralewski diagram (2026-04-19).",
        1.2822,
        1.216,
    ),
    "H2O": Gas(
        "Water",
        "H2O",
        72.0,
        8000,
        273.0,
        644.0,
        6.3,
        6000.0,
        0.018,
        18.01,
        373.15,
        "Phase curve: zgralewski diagram (2026-04-19).",
        1.5942,
        1.2833,
    ),
    "SIL": Gas(
        "Silanol",
        "Sil",
        None,
        10000,
        164.0,
        822.0,
        516.0,
        6000.0,
        0.16,
        None,
        None,
        "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
        2.0,
        1.3887,
    ),
    "ALC": Gas(
        "Alcohol",
        "ALC",
        None,
        None,
        232.0,
        424.0,
        6.3,
        1000.0,
        None,
        None,
        None,
        "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
        1.3606,
        1.2204,
    ),
    "HCl": Gas(
        "Hydrochloric Acid",
        "HCl",
        None,
        None,
        247.0,
        431.0,
        6.3,
        1000.0,
        None,
        None,
        None,
        "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
        1.3058,
        1.214,
    ),
    "O3": Gas(
        "Ozone",
        "O3",
        None,
        None,
        81.0,
        304.0,
        250.0,
        6000.0,
        None,
        None,
        None,
        "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
        1.8627,
        1.369,
    ),
    "N2H4": Gas(
        "Hydrazine / Fuel",
        "N2H4",
        None,
        None,
        246.0,
        521.0,
        6.3,
        6000.0,
        None,
        None,
        None,
        "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
        1.4565,
        1.2715,
    ),
}

_ALIASES = {
    "POLLUTANT": "X",
    "METHANE": "CH4",
    "VOLATILES": "CH4",
    "NITROGEN": "N2",
    "OXYGEN": "O2",
    "HYDROGEN": "H2",
    "HELIUM": "HE",
    "HE": "HE",
    "WATER": "H2O",
    "STEAM": "H2O",
    "SILANOL": "SIL",
    "SIL": "SIL",
    "ALCOHOL": "ALC",
    "NITROUS": "N2O",
    "NITROUS OXIDE": "N2O",
    "CARBON DIOXIDE": "CO2",
    "HYDRAZINE": "N2H4",
    "FUEL": "N2H4",
    "OZONE": "O3",
    "ACID": "HCL",
    "HCL": "HCL",
}


def get_gas(key: str) -> Gas:
    raw = key.strip()
    upper = raw.upper().replace(" ", "")
    if upper in GASES:
        return GASES[upper]
    alias = _ALIASES.get(raw.upper()) or _ALIASES.get(upper)
    if alias == "HCL":
        return GASES["HCl"]
    if alias and alias in GASES:
        return GASES[alias]
    for g in GASES.values():
        if g.symbol.upper() == upper or g.name.upper() == raw.upper():
            return g
    raise KeyError(f"unknown media {key!r}; known: {sorted(GASES)}")
