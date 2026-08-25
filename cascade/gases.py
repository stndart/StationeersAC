"""Gas table and saturation-pressure interpolation."""

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
    extra_points: tuple[tuple[float, float], ...] = ()

    def anchors(self) -> list[tuple[float, float]]:
        pts: list[tuple[float, float]] = []
        if self.t_freeze is not None and self.p_min_cond is not None:
            pts.append((self.t_freeze, self.p_min_cond))
        pts.extend(self.extra_points)
        if self.boil_100kpa is not None:
            pts.append((self.boil_100kpa, 100.0))
        if self.t_crit is not None and self.p_crit is not None:
            pts.append((self.t_crit, self.p_crit))
        pts.sort(key=lambda tp: tp[0])
        mono: list[tuple[float, float]] = []
        for t, p in pts:
            if any(abs(t - mt) < 0.5 for mt, _ in mono):
                continue
            if mono and p <= mono[-1][1] * 0.98:
                continue
            mono.append((t, p))
        if len(mono) < 2:
            raise ValueError(f"{self.symbol}: need ≥2 saturation anchors")
        return mono

    def _segment(self, t: float) -> tuple[float, float, float, float]:
        a = self.anchors()
        if t <= a[0][0]:
            (t1, p1), (t2, p2) = a[0], a[1]
        elif t >= a[-1][0]:
            (t1, p1), (t2, p2) = a[-2], a[-1]
        else:
            t1, p1 = a[0]
            t2, p2 = a[1]
            for i in range(len(a) - 1):
                if a[i][0] <= t <= a[i + 1][0]:
                    t1, p1 = a[i]
                    t2, p2 = a[i + 1]
                    break
        return t1, p1, t2, p2

    def p_sat(self, t: float) -> float:
        """log10(P) linear in T through anchors (chart-style)."""
        t1, p1, t2, p2 = self._segment(t)
        frac = 0.0 if t2 == t1 else (t - t1) / (t2 - t1)
        logp = math.log10(p1) + frac * (math.log10(p2) - math.log10(p1))
        return 10.0**logp

    def t_sat(self, p: float) -> float:
        a = self.anchors()
        logp = math.log10(max(p, 1e-9))
        if logp <= math.log10(a[0][1]):
            t1, p1 = a[0]
            t2, p2 = a[1]
        elif logp >= math.log10(a[-1][1]):
            t1, p1 = a[-2]
            t2, p2 = a[-1]
        else:
            t1, p1 = a[0]
            t2, p2 = a[1]
            for i in range(len(a) - 1):
                if a[i][1] <= p <= a[i + 1][1]:
                    t1, p1 = a[i]
                    t2, p2 = a[i + 1]
                    break
        frac = (logp - math.log10(p1)) / (math.log10(p2) - math.log10(p1))
        return t1 + frac * (t2 - t1)

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
        40.01,
        190.0,
        6.3,
        6000,
        0.0348,
        28.02,
        75.0,
        "Wiki table + chart.",
        extra_points=((75.0, 100.0),),
    ),
    "O2": Gas(
        "Oxygen",
        "O2",
        21.1,
        800,
        56.416,
        162.2,
        6.3,
        6000,
        0.03,
        15.99,
        90.0,
        "Wiki table. Chart extra: 81 K / 250 kPa.",
        extra_points=((81.0, 250.0),),
    ),
    "CH4": Gas(
        "Methane / Volatiles",
        "CH4",
        20.4,
        1000,
        81.6,
        195.0,
        6.3,
        6000,
        0.04,
        16.04,
        112.0,
        "Chart CH4 matches old Volatiles phase data.",
        extra_points=((91.0, 6.0),),
    ),
    "H2": Gas(
        "Hydrogen",
        "H2",
        20.4,
        None,
        15.0,
        70.0,
        6.0,
        6000,
        None,
        2.0,
        None,
        "Chart 2026-04-19. Coupling gas / LH2; not a -180 C refrigerant.",
    ),
    "X": Gas(
        "Pollutant",
        "X",
        24.8,
        2000,
        173.32,
        425.0,
        1800,
        6000,
        0.04,
        64.0,
        None,
        "Min condensation 1.8 MPa at freeze. Typical stage-1 media.",
        extra_points=((173.0, 1800.0),),
    ),
    "CO2": Gas(
        "Carbon Dioxide",
        "CO2",
        28.2,
        600,
        217.82,
        265.0,
        517,
        6000,
        0.04,
        44.01,
        None,
        "T_crit -8 C: cannot dump at +40 C.",
    ),
    "N2O": Gas(
        "Nitrous Oxide",
        "N2O",
        37.2,
        4000,
        252.1,
        430.6,
        800,
        2000,
        0.026,
        46.0,
        None,
        "Dumps at +40 C but freeze -21 C.",
    ),
    "H2O": Gas(
        "Water",
        "H2O",
        72.0,
        8000,
        273.15,
        643.0,
        6.3,
        6000,
        0.018,
        18.01,
        373.15,
        "Freezes at 0 C.",
    ),
    "SIL": Gas(
        "Silanol",
        "Sil",
        None,
        10000,
        164.0,
        821.669,
        516,
        6000,
        0.16,
        None,
        None,
        "Late-game stage-1. Missing SHC — CFHE parasitic assumed 0.",
    ),
    "ALC": Gas(
        "Alcohol",
        "ALC",
        None,
        None,
        232.0,
        424.0,
        6.0,
        1000,
        None,
        None,
        None,
        "Chart only. Missing L / V_liq / SHC.",
    ),
    "HCl": Gas(
        "Hydrochloric Acid",
        "HCl",
        None,
        None,
        247.0,
        431.0,
        6.0,
        2000,
        None,
        None,
        None,
        "Chart only. Missing L / V_liq / SHC.",
    ),
    "O3": Gas(
        "Ozone",
        "O3",
        None,
        None,
        None,
        304.0,
        None,
        6000,
        None,
        None,
        None,
        "T_crit 31 C. Cannot dump at +40 C.",
    ),
    "N2H4": Gas(
        "Hydrazine / Fuel",
        "N2H4",
        None,
        None,
        None,
        521.0,
        None,
        6000,
        None,
        None,
        None,
        "Hypergolic / toxic — do not use as AC media.",
    ),
}

_ALIASES = {
    "POLLUTANT": "X",
    "METHANE": "CH4",
    "VOLATILES": "CH4",
    "NITROGEN": "N2",
    "OXYGEN": "O2",
    "HYDROGEN": "H2",
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
