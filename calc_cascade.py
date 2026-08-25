"""Stationeers multi-step phase-change AC cascade calculator.

Target: liquid nitrogen / cold bus at about -180 C, heat dump at +40 C
via pipe convection radiators (any count on one pipe).

Energy is reported as kJ/tick (Stationeers atmospherics tick) and as
kW_SI assuming 0.5 s/tick (wiki Physics: 1 tick = 0.5 s; in-game Watt = J/tick).

Sources: stationeers-wiki Gas / Phase Change / Silanol / Evaporation Chamber /
Thermal convection values; Niilo007 Stationeers-Research wiki; RA2lover
thermodynamics notes; player chart Gasses-2026-04-19.png (2026-04-19).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

OUT = Path(__file__).resolve().parent
TICK_S = 0.5  # seconds per atmospherics tick
R = 8.314462618  # J/(mol K)
P_ATM = 101.325  # kPa
LIQUID_FEED_L_PER_TICK = 0.25  # evaporation chamber liquid volume regulator
CHAMBER_HX_M2 = 15.0
CFHE_PER_TRANSFER_W = 15.625  # game W = J/tick
CFHE_TRANSFERS = 48
CFHE_ETA_PER_UNIT = 0.70  # steam news / wiki: ~70% temp swap per exchanger
# Convection: E(J/tick) = ThermalConvection * 50 * clamp(P/atm) * clamp(P/atm) * dT
PIPE_CONV_THERMAL = 1.05  # pipe convection radiator (gas)
LIQUID_PIPE_CONV_THERMAL = 1.02
CHAMBER_HX_J_PER_TICK_K = 100.0 * CHAMBER_HX_M2 * TICK_S  # 750 J/tick/K at 1 atm both sides
RAD_J_PER_TICK_K = PIPE_CONV_THERMAL * 50.0  # 52.5 J/tick/K
CFHE_J_PER_TICK_K = CFHE_PER_TRANSFER_W * CFHE_TRANSFERS  # 750 J/tick/K


@dataclass
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
    boil_100kpa: float | None  # K, wiki (often slightly off vs in-game)
    notes: str
    extra_points: tuple[tuple[float, float], ...] = ()  # (T_K, P_kPa) chart anchors

    def anchors(self) -> list[tuple[float, float]]:
        """Monotonic (T, P) knots for piecewise log-P interpolation.

        Prefer chart extra-points. Wiki 100 kPa boiling points are documented as
        slightly wrong — keep them only when they do not break P increasing with T.
        """
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
                continue  # drop non-monotonic wiki boil vs chart
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

    def p_sat_log_t(self, t: float) -> float:
        """Piecewise log10(P) linear in T through anchors (chart-style)."""
        t1, p1, t2, p2 = self._segment(t)
        frac = 0.0 if t2 == t1 else (t - t1) / (t2 - t1)
        logp = math.log10(p1) + frac * (math.log10(p2) - math.log10(p1))
        return 10.0**logp

    def t_sat_log_t(self, p: float) -> float:
        a = self.anchors()
        logp = math.log10(p)
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

    def p_sat_antoine(self, t: float) -> float:
        """Piecewise ln(P) linear in 1/T through the same anchors."""
        t1, p1, t2, p2 = self._segment(t)
        ln1, ln2 = math.log(p1), math.log(p2)
        inv1, inv2 = 1.0 / t1, 1.0 / t2
        b = (ln2 - ln1) / (inv1 - inv2)
        aa = ln1 + b * inv1
        return math.exp(aa - b / t)

    def mol_per_tick_feed(self) -> float:
        return LIQUID_FEED_L_PER_TICK / self.v_liq

    def q_latent_kj_tick(self) -> float:
        return self.mol_per_tick_feed() * self.latent / 1000.0


GASES = {
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
        "Wiki table + chart. MW from research wiki (community wiki scrape sometimes lists 64).",
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
        "Post-2026 split: chart CH4 matches old Volatiles phase data (195 K @ 6 MPa, freeze 81.6 K).",
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
        "Chart 2026-04-19: 15 K @ 6 kPa, 70 K @ 6 MPa. Lowest freeze. Cannot condense until -203 C — coupling gas / LH2 only, not a -180 C refrigerant.",
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
        "Min condensation 1.8 MPa at freeze — always a high-pressure liquid. Only common gas that both dumps at +40 C and reaches CH4/N2 condenser temps.",
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
        "T_crit -8 C: cannot dump at +40 C. Freeze = min-cond T: dry-ice pipe risk.",
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
        "Can dump at +40 C but freeze -21 C — cannot condense CH4/N2. Strong latent, useful only as a warm extra stage.",
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
        "Huge latent, freezes at 0 C. Not a cascade refrigerant below ambient. HX port on chambers is gas-only so dump loop cannot be liquid water.",
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
        "Wiki: highest latent of reversible refrigerants; 6.25 mol/L; 15.625 kJ/tick at 0.25 L/tick. Chart: 822 K @ 6 MPa, 164 K @ 516 kPa (used as freeze/min-cond). Late-game.",
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
        "Chart only: 232 K @ 6 kPa, 424 K @ 1.0 MPa. Liquid at +40 C but freeze ~-41 C — cannot reach CH4/N2. Vacuum decomposes to methane.",
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
        "Chart: 247 K @ 6 kPa, 431 K @ ~1-2 MPa. Similar window to N2O/alcohol. Wiki: inferior to N2O/Silanol/X for phase change.",
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
        "Chart: T_crit 304 K (31 C) @ 6 MPa. Cannot condense at +40 C under 6 MPa.",
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
        "Chart: 521 K @ 6 MPa. Liquid at room T. Hypergolic / toxic — do not use as AC media.",
    ),
}


def c(k: float) -> float:
    return k - 273.15


def k_from_c(tc: float) -> float:
    return tc + 273.15


def cfhe_eta(n: int) -> float:
    return 1.0 - (1.0 - CFHE_ETA_PER_UNIT) ** n


def useful_frac(gas: Gas, t_cond: float, t_evap: float, n_cfhe: int) -> float:
    """Fraction of latent heat left after cooling incoming liquid (CFHE residual)."""
    if gas.shc is None or gas.latent is None:
        return 1.0  # unknown SHC: report raw latent and flag in notes
    eta = cfhe_eta(n_cfhe)
    sensible = gas.shc * (t_cond - t_evap)
    parasitic = sensible * (1.0 - eta)
    return 1.0 - parasitic / gas.latent


def clamp01_atm(p_kpa: float) -> float:
    return max(0.0, min(p_kpa / P_ATM, 1.0))


def chamber_hx_kj_tick(dt: float, p_a: float, p_b: float) -> float:
    return CHAMBER_HX_J_PER_TICK_K * dt * clamp01_atm(p_a) * clamp01_atm(p_b) / 1000.0


def rad_kj_tick(dt: float, p_pipe: float, p_room: float) -> float:
    return RAD_J_PER_TICK_K * dt * clamp01_atm(p_pipe) * clamp01_atm(p_room) / 1000.0


def kj_tick_to_kw_si(q: float) -> float:
    return q / TICK_S


@dataclass
class Stage:
    tag: str
    gas: str
    t_cond: float
    t_evap: float
    n_cfhe: int
    p_coupling_in: float  # kPa, condenser HX loop
    p_coupling_out: float  # kPa, evaporator HX loop
    hx_dt_cond: float  # K, chamber vs dump/coupling
    hx_dt_evap: float


def stage_report(st: Stage) -> dict:
    g = GASES[st.gas]
    p_cond = g.p_sat_log_t(st.t_cond)
    p_evap = g.p_sat_log_t(st.t_evap)
    p_cond_an = g.p_sat_antoine(st.t_cond)
    p_evap_an = g.p_sat_antoine(st.t_evap)
    eta = cfhe_eta(st.n_cfhe)
    uf = useful_frac(g, st.t_cond, st.t_evap, st.n_cfhe)
    q_lat = g.q_latent_kj_tick()
    q_use = q_lat * uf
    q_hx_c = chamber_hx_kj_tick(st.hx_dt_cond, st.p_coupling_in, p_cond)
    q_hx_e = chamber_hx_kj_tick(st.hx_dt_evap, st.p_coupling_out, p_evap)
    # liquid-pipe "pressure" for HX is not p_sat; chamber HX is gas port.
    freeze_margin = st.t_evap - g.t_freeze
    crit_margin = g.t_crit - st.t_cond
    sensible_over_l = (
        None
        if g.shc is None or g.latent is None
        else g.shc * (st.t_cond - st.t_evap) / g.latent
    )
    limits = {
        "liquid_feed_useful_kj_tick": q_use,
        "chamber_hx_cond_kj_tick": q_hx_c,
        "chamber_hx_evap_kj_tick": q_hx_e,
    }
    bottleneck = min(limits, key=limits.get)
    return {
        "tag": st.tag,
        "media": g.name,
        "symbol": g.symbol,
        "t_cond_K": round(st.t_cond, 2),
        "t_cond_C": round(c(st.t_cond), 2),
        "t_evap_K": round(st.t_evap, 2),
        "t_evap_C": round(c(st.t_evap), 2),
        "p_cond_kPa_logT": round(p_cond, 1),
        "p_evap_kPa_logT": round(p_evap, 1),
        "p_cond_kPa_Antoine": round(p_cond_an, 1),
        "p_evap_kPa_Antoine": round(p_evap_an, 1),
        "n_cfhe": st.n_cfhe,
        "cfhe_eta": round(eta, 4),
        "sensible_over_latent": None if sensible_over_l is None else round(sensible_over_l, 3),
        "useful_frac": round(uf, 4),
        "mol_tick_feed": round(g.mol_per_tick_feed(), 4),
        "q_latent_kj_tick": round(q_lat, 3),
        "q_useful_kj_tick": round(q_use, 3),
        "q_useful_kW_SI": round(kj_tick_to_kw_si(q_use), 3),
        "q_hx_cond_kj_tick": round(q_hx_c, 3),
        "q_hx_evap_kj_tick": round(q_hx_e, 3),
        "freeze_margin_K": round(freeze_margin, 2),
        "crit_margin_K": round(crit_margin, 2),
        "stage_bottleneck": bottleneck,
        "stage_limit_kj_tick": round(limits[bottleneck], 3),
    }


# --- recommended operating points ---
# Room dump +40 C. Condenser HX loop held ~55 C so radiators see 15 K.
# Pollutant evaporator parked ~10 K above freeze to leave HX dT for CH4 cond.
T_ROOM = k_from_c(40.0)
T_DUMP_LOOP = k_from_c(55.0)
T_X_COND = k_from_c(70.0)  # 15 K above dump loop for 15 m2 chamber HX
T_X_EVAP = k_from_c(-93.0)  # 173 K freeze + ~7 K
T_CH4_COND = k_from_c(-83.0)  # 190 K, 5 K below CH4 crit 195 K
T_CH4_EVAP_2ST = k_from_c(-185.0)  # 2-stage last evap
T_CH4_EVAP_3ST = k_from_c(-145.0)
T_N2_COND_3ST = k_from_c(-135.0)
T_N2_EVAP = k_from_c(-185.0)
T_N2_COND_2ST = k_from_c(-88.0)  # tight against 190 K crit
T_LOAD = k_from_c(-180.0)

CASCADES = {
    "A_two_stage_X_CH4": [
        Stage("S1 dump", "X", T_X_COND, T_X_EVAP, 3, 300.0, 300.0, 15.0, 8.0),
        Stage("S2 cryo", "CH4", T_CH4_COND, T_CH4_EVAP_2ST, 3, 300.0, 200.0, 8.0, 8.0),
    ],
    "B_two_stage_X_N2": [
        Stage("S1 dump", "X", T_X_COND, T_X_EVAP, 3, 300.0, 300.0, 15.0, 5.0),
        Stage("S2 cryo", "N2", T_N2_COND_2ST, T_N2_EVAP, 4, 250.0, 200.0, 5.0, 8.0),
    ],
    "C_three_stage_X_CH4_N2": [
        Stage("S1 dump", "X", T_X_COND, T_X_EVAP, 2, 300.0, 300.0, 15.0, 8.0),
        Stage("S2 mid", "CH4", T_CH4_COND, T_CH4_EVAP_3ST, 2, 300.0, 250.0, 8.0, 8.0),
        Stage("S3 cryo", "N2", T_N2_COND_3ST, T_N2_EVAP, 3, 250.0, 200.0, 8.0, 8.0),
    ],
    "D_late_silanol_N2": [
        Stage("S1 dump", "SIL", k_from_c(70.0), k_from_c(-100.0), 3, 300.0, 300.0, 15.0, 10.0),
        Stage("S2 cryo", "N2", k_from_c(-88.0), T_N2_EVAP, 4, 250.0, 200.0, 8.0, 8.0),
    ],
}


def rejected_media() -> list[dict]:
    rows = []
    need_cond_min = T_ROOM + 10.0  # must still be liquid ~10 K above room
    need_evap_max = GASES["CH4"].t_crit - 8.0  # must cool a CH4/N2 condenser
    for g in GASES.values():
        can_dump = g.t_crit is not None and g.t_crit > need_cond_min
        can_reach_cryo_cond = g.t_freeze is not None and g.t_freeze < need_evap_max
        role = []
        if can_dump and can_reach_cryo_cond:
            role.append("STAGE-1 capable")
        elif can_dump:
            role.append("warm-only (cannot couple to CH4/N2)")
        elif g.t_crit is not None and g.t_crit < T_ROOM:
            role.append("cannot dump at +40 C")
        if g.t_crit is not None and g.t_freeze is not None:
            if g.t_crit > T_LOAD + 10 and g.t_freeze < T_LOAD - 5:
                role.append("STAGE-last capable for -180 C")
        rows.append(
            {
                "symbol": g.symbol,
                "name": g.name,
                "t_freeze_C": None if g.t_freeze is None else round(c(g.t_freeze), 1),
                "t_crit_C": None if g.t_crit is None else round(c(g.t_crit), 1),
                "can_dump_40C": can_dump,
                "can_reach_CH4_cond": can_reach_cryo_cond,
                "role": ", ".join(role) if role else "not useful here",
                "notes": g.notes,
            }
        )
    return rows


def saturation_table(symbol: str, temps_c: list[float]) -> list[dict]:
    g = GASES[symbol]
    rows = []
    for tc in temps_c:
        t = k_from_c(tc)
        if g.t_freeze is None or g.t_crit is None:
            continue
        if t < g.t_freeze or t > g.t_crit:
            rows.append(
                {
                    "T_C": tc,
                    "T_K": round(t, 2),
                    "in_liquid_window": False,
                    "p_logT_kPa": None,
                    "p_Antoine_kPa": None,
                    "reason": "below freeze" if t < g.t_freeze else "above T_crit",
                }
            )
            continue
        rows.append(
            {
                "T_C": tc,
                "T_K": round(t, 2),
                "in_liquid_window": True,
                "p_logT_kPa": round(g.p_sat_log_t(t), 2),
                "p_Antoine_kPa": round(g.p_sat_antoine(t), 2),
                "reason": "ok",
            }
        )
    return rows


def dump_radiators_for(q_kj_tick: float, t_loop: float, t_room: float, p_pipe: float, p_room: float) -> dict:
    dt = t_loop - t_room
    q1 = rad_kj_tick(dt, p_pipe, p_room)
    n = math.ceil(q_kj_tick / q1) if q1 > 0 else None
    return {
        "dt_K": round(dt, 2),
        "q_per_radiator_kj_tick": round(q1, 4),
        "q_per_radiator_kW_SI": round(kj_tick_to_kw_si(q1), 4),
        "radiators_needed": n,
        "note": "Not the cascade bottleneck: user can add any number on one pipe. Size for the heat the stages actually pump.",
    }


def cascade_summary(name: str, stages: list[Stage]) -> dict:
    reports = [stage_report(s) for s in stages]
    # heat pumped is limited by the minimum useful stage limit along the chain
    # (steady state: each stage must move the load heat plus CFHE/pump overhead;
    # we treat useful evaporator cooling of the last stage as the product rating,
    # and require upstream stages' limits >= that.)
    last = reports[-1]
    q_load = last["q_useful_kj_tick"]
    upstream_ok = []
    for r in reports:
        ok = r["stage_limit_kj_tick"] + 1e-9 >= q_load
        upstream_ok.append({"tag": r["tag"], "limit": r["stage_limit_kj_tick"], "covers_load": ok})
    rad = dump_radiators_for(reports[0]["q_useful_kj_tick"], T_DUMP_LOOP, T_ROOM, 300.0, 101.325)
    chain_limit = min(r["stage_limit_kj_tick"] for r in reports)
    chain_bot = min(reports, key=lambda r: r["stage_limit_kj_tick"])
    rad_chain = dump_radiators_for(chain_limit, T_DUMP_LOOP, T_ROOM, 300.0, 101.325)
    return {
        "name": name,
        "stages": reports,
        "load_q_kj_tick": q_load,
        "load_q_kW_SI": kj_tick_to_kw_si(q_load),
        "chain_limit_kj_tick": chain_limit,
        "chain_bottleneck_stage": chain_bot["tag"],
        "chain_bottleneck_kind": chain_bot["stage_bottleneck"],
        "upstream_covers_load": upstream_ok,
        "dump_radiators": rad,
        "dump_radiators_for_chain_limit": rad_chain,
        "ln2_product": ln2_product_note(name),
    }


def ln2_product_note(name: str) -> dict:
    n2 = GASES["N2"]
    p = n2.p_sat_log_t(T_LOAD)
    p_an = n2.p_sat_antoine(T_LOAD)
    return {
        "target_C": -180.0,
        "target_K": T_LOAD,
        "p_sat_logT_kPa": round(p, 2),
        "p_sat_Antoine_kPa": round(p_an, 2),
        "wiki_boil_100kPa_C": round(c(n2.boil_100kpa), 1),
        "how": (
            "Tap LN2 from the N2 condensation chamber liquid output if N2 is a refrigerant stage; "
            "otherwise hang a dedicated N2 condenser on the last-stage evaporator HX (H2 coupling gas)."
        ),
    }


def fmt_table(rows: list[dict], keys: list[str]) -> str:
    if not rows:
        return ""
    widths = {k: max(len(k), max(len(str(r.get(k, ""))) for r in rows)) for k in keys}
    head = " | ".join(k.ljust(widths[k]) for k in keys)
    sep = "-+-".join("-" * widths[k] for k in keys)
    body = "\n".join(" | ".join(str(r.get(k, "")).ljust(widths[k]) for k in keys) for r in rows)
    return f"{head}\n{sep}\n{body}"


def md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def main() -> None:
    rejected = rejected_media()
    sat = {
        "X": saturation_table("X", [40, 55, 70, 100, -80, -90, -93, -99]),
        "CH4": saturation_table("CH4", [-78, -83, -90, -120, -145, -173, -180, -185, -191]),
        "N2": saturation_table("N2", [-83, -88, -100, -135, -160, -180, -185, -198, -220]),
        "O2": saturation_table("O2", [-111, -140, -180, -192]),
        "SIL": saturation_table("SIL", [70, 40, -80, -100, -109]),
        "N2O": saturation_table("N2O", [40, 70, 0, -15, -21]),
        "ALC": saturation_table("ALC", [40, 70, 0, -30, -41]),
    }
    cascades = {k: cascade_summary(k, v) for k, v in CASCADES.items()}

    # coupling windows
    x = GASES["X"]
    ch4 = GASES["CH4"]
    n2 = GASES["N2"]
    sil = GASES["SIL"]
    windows = {
        "X_evap_min_C": round(c(x.t_freeze), 2),
        "CH4_cond_max_C": round(c(ch4.t_crit), 2),
        "N2_cond_max_C": round(c(n2.t_crit), 2),
        "X_to_CH4_window_K": round(ch4.t_crit - x.t_freeze, 2),
        "X_to_N2_window_K": round(n2.t_crit - x.t_freeze, 2),
        "SIL_to_N2_window_K": round(n2.t_crit - sil.t_freeze, 2),
        "O2_crit_C": round(c(GASES["O2"].t_crit), 2),
        "X_cannot_condense_O2": True,
        "comment": (
            "Pollutant freeze (-99.8 C) is below CH4 crit (-78 C) and N2 crit (-83 C), "
            "so X can condense those. O2 crit is -111 C — colder than X freeze — so X cannot condense O2. "
            "Alcohol/N2O/HCl freeze too warm to condense CH4/N2. Ozone/CO2 cannot dump at +40 C."
        ),
    }

    constants = {
        "tick_s": TICK_S,
        "liquid_feed_L_tick": LIQUID_FEED_L_PER_TICK,
        "chamber_hx_m2": CHAMBER_HX_M2,
        "chamber_hx_J_tick_K_at_1atm": CHAMBER_HX_J_PER_TICK_K,
        "radiator_J_tick_K_at_1atm": RAD_J_PER_TICK_K,
        "cfhe_J_tick_K": CFHE_J_PER_TICK_K,
        "cfhe_eta_per_unit": CFHE_ETA_PER_UNIT,
        "room_C": 40.0,
        "dump_loop_C": round(c(T_DUMP_LOOP), 2),
        "load_C": -180.0,
        "hx_derate": "Heat exchange scales with clamp(P/101.325 kPa, 0..1) on BOTH sides. Keep coupling loops >= 150 kPa (wiki) and ideally >= 1 atm.",
        "evap_chamber": "0.25 L/tick liquid regulator targeting 20 L (10%). Gas purge ~15 MPa*L/tick. HX area 15 m2.",
        "cfhe": "Balances pressure / liquid fraction, then 48 sliding-window transfers at 15.625 W*dT*eta. ~70% temp swap per unit; daisy-chain.",
    }

    payload = {
        "constants": constants,
        "coupling_windows": windows,
        "media_roles": rejected,
        "saturation": sat,
        "cascades": cascades,
        "recommendation": "C_three_stage_X_CH4_N2",
        "recommendation_why": (
            "Two-stage X+CH4 works but the CH4 evaporator sits near 6 kPa at -185 C (freeze 81.6 K), "
            "which starves evaporation rate. Two-stage X+N2 has only ~17 K between X freeze and N2 crit, "
            "so HX dT is tight and freeze risk is real. Three-stage X / CH4 / N2 opens both windows, "
            "keeps N2 evaporator at a usable tens-of-kPa, and makes the N2 condenser the LN2 tap."
        ),
    }

    (OUT / "cascade_numbers.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # human-readable results
    lines: list[str] = []
    a = lines.append
    a("# Stationeers LN2 / -180 C cascade — calculation results")
    a("")
    a("Generated by `calc_cascade.py`. Re-run that script after changing operating points.")
    a("")
    a("## 0. What is being solved")
    a("")
    a("- **Load:** cold bus at **-180 C (93.15 K)**, optionally tapping **liquid nitrogen**.")
    a("- **Sink:** room / box at **+40 C**, heat rejected by **pipe convection radiators** (any number on one pipe).")
    a("- **Machine:** each stage is `Evaporation Chamber` + `Condensation Chamber` + **Counterflow Heat Exchanger(s)** on the refrigerant path between them.")
    a("- **Energy unit:** **kJ per atmospherics tick**. `kW_SI = (kJ/tick) / 0.5 s`. In-game Watt is J/tick, so game-kW equals kJ/tick.")
    a("")
    a("## 1. Constants used")
    a("")
    for k, v in constants.items():
        a(f"- `{k}`: {v}")
    a("")
    a("Chamber HX throughput at 1 atm both sides: **750 J/tick/K** (100 W/m2/K * 15 m2 * 0.5 s).")
    a("One gas pipe convection radiator: **52.5 J/tick/K** (ThermalConvection 1.05 * 50).")
    a("")
    a("## 2. Why most gases cannot be stage 1")
    a("")
    a("Stage 1 must (a) still be liquid at ~+50–70 C under ≤ 6 MPa, and (b) evaporate colder than CH4 crit **(-78 C)** or N2 crit **(-83 C)** so the next condenser can actually make liquid.")
    a("")
    a("| symbol | freeze C | crit C | dump +40 C | reach CH4/N2 cond | role |")
    a("|---|---:|---:|---|---|---|")
    for r in rejected:
        a(
            f"| {r['symbol']} | {r['t_freeze_C']} | {r['t_crit_C']} | {r['can_dump_40C']} | {r['can_reach_CH4_cond']} | {r['role']} |"
        )
    a("")
    a("**Coupling windows (K between previous freeze and next T_crit):**")
    a("")
    a(f"- X → CH4: **{windows['X_to_CH4_window_K']} K** (usable)")
    a(f"- X → N2: **{windows['X_to_N2_window_K']} K** (tight)")
    a(f"- Silanol → N2: **{windows['SIL_to_N2_window_K']} K** (comfortable, late-game)")
    a("- X → O2: **impossible** (O2 crit -111 C is below X freeze -99.8 C)")
    a("")
    a(windows["comment"])
    a("")
    a("## 3. Saturation tables (intermediate)")
    a("")
    a("Two interpolations through the same piecewise anchors (freeze, chart points, wiki 100 kPa boil if monotonic, critical): **log10(P) vs T** and **ln(P) vs 1/T**. Set chamber pressure from the log-T column, then trim in-game. Wiki 100 kPa boiling points are documented as slightly wrong and are dropped when they contradict chart points.")
    a("")
    for sym, rows in sat.items():
        a(f"### {sym}")
        a("")
        a("| T C | T K | liquid? | P kPa logT | P kPa Antoine | note |")
        a("|---:|---:|---|---:|---:|---|")
        for r in rows:
            a(
                f"| {r['T_C']} | {r['T_K']} | {r['in_liquid_window']} | {r['p_logT_kPa']} | {r['p_Antoine_kPa']} | {r['reason']} |"
            )
        a("")

    n2p = n2.p_sat_log_t(T_LOAD)
    a("### LN2 at -180 C")
    a("")
    a(f"- P_sat logT = **{n2p:.1f} kPa**")
    a(f"- P_sat Antoine = **{n2.p_sat_antoine(T_LOAD):.1f} kPa**")
    a(f"- Wiki 100 kPa boil = **{c(n2.boil_100kpa):.1f} C** (75 K). -180 C is warmer than that boil point, so LN2 at the target is a *pressurized* liquid: about **{n2p:.0f} kPa** (logT), not 6 MPa and not a few kPa.")
    a("")

    a("## 4. Per-stage heat budget formula")
    a("")
    a("```")
    a("mol/tick     = 0.25 L/tick / V_liquid")
    a("Q_latent     = mol/tick * L")
    a("eta_CFHE     = 1 - 0.30^n          # 70% temperature recovery per unit")
    a("Q_parasitic  = mol/tick * c_p * (T_cond - T_evap) * (1 - eta_CFHE)")
    a("Q_useful     = Q_latent - Q_parasitic")
    a("Q_chamberHX  = 0.750 kJ/tick/K * dT * clamp(P_hx/atm) * clamp(P_ch/atm)")
    a("Q_radiator   = 0.0525 kJ/tick/K * dT * clamp(P_pipe/atm) * clamp(P_room/atm)")
    a("```")
    a("")
    a("If `c_p * dT / L` is large (N2, CH4 spanning 100 K), CFHE is mandatory. One unit is not enough for the cryo stage.")
    a("")

    a("## 5. Cascade options (final numbers)")
    a("")
    for name, cas in cascades.items():
        rec = "  **← recommended**" if name == payload["recommendation"] else ""
        a(f"### {name}{rec}")
        a("")
        a(
            f"Load rating (last-stage Q_useful): **{cas['load_q_kj_tick']:.3f} kJ/tick** "
            f"= **{cas['load_q_kW_SI']:.2f} kW_SI**"
        )
        a(
            f"Chain bottleneck: **{cas['chain_bottleneck_stage']} / {cas['chain_bottleneck_kind']}** "
            f"at {cas['chain_limit_kj_tick']:.3f} kJ/tick"
        )
        a("")
        a("| stage | media | Tcond C | Tevap C | Pcond kPa | Pevap kPa | CFHE n | eta | Qlat | Quse | HXcond | HXevap | freeze K | crit K | bottleneck |")
        a("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
        for s in cas["stages"]:
            a(
                f"| {s['tag']} | {s['symbol']} | {s['t_cond_C']} | {s['t_evap_C']} | {s['p_cond_kPa_logT']} | {s['p_evap_kPa_logT']} | {s['n_cfhe']} | {s['cfhe_eta']} | {s['q_latent_kj_tick']} | {s['q_useful_kj_tick']} | {s['q_hx_cond_kj_tick']} | {s['q_hx_evap_kj_tick']} | {s['freeze_margin_K']} | {s['crit_margin_K']} | {s['stage_bottleneck']} |"
            )
        a("")
        d = cas["dump_radiators"]
        a(
            f"Dump radiators for this cascade's S1 useful heat, loop at {c(T_DUMP_LOOP):.0f} C vs room 40 C: "
            f"**{d['radiators_needed']}** gas pipe convection radiators "
            f"({d['q_per_radiator_kj_tick']} kJ/tick each). {d['note']}"
        )
        a("")
        a(cas["ln2_product"]["how"])
        a("")

    a("## 6. Recommended schema (option C)")
    a("")
    a("```")
    a("ROOM +40 C  (>= 1 atm)")
    a("  N x Pipe Convection Radiator  on ONE gas pipe")
    a("  dump gas: Pollutant or N2O, 300 kPa, loop ~55 C")
    a("        |  (chamber HX port, 15 m2)")
    a("S1 COND  Pollutant   70 C   ~ 3.8 MPa   (logT)")
    a("        |  gas up")
    a("     CFHE x2  (liquid down / vapor up, matched mol/tick)")
    a("        |  liquid down")
    a("S1 EVAP  Pollutant  -93 C   ~ 1.9 MPa")
    a("        |  coupling gas: Pollutant, 300 kPa  (below X P_sat, above 1 atm)")
    a("S2 COND  CH4        -83 C   ~ 4.7 MPa")
    a("        |")
    a("     CFHE x2")
    a("        |")
    a("S2 EVAP  CH4       -145 C   ~ 0.22 MPa")
    a("        |  coupling gas: N2 or H2, >= 200 kPa")
    a("S3 COND  N2        -135 C   ~ 0.7 MPa     *** LN2 TAP (liquid output) ***")
    a("        |")
    a("     CFHE x3")
    a("        |")
    a("S3 EVAP  N2        -185 C   ~ 0.16 MPa")
    a("        |  cold bus: Hydrogen >= 150 kPa  (will not condense at -180 C)")
    a("LOAD / extra N2 condenser at -180 C")
    a("```")
    a("")
    a("Each condenser-evaporator pair is its own closed refrigerant inventory. Stages only exchange **heat** through the HX ports.")
    a("")
    a("## 7. Heat-flow bottleneck ranking (recommended build, 1 chamber per end)")
    a("")
    rec = cascades["C_three_stage_X_CH4_N2"]
    a("Steady state the whole cascade cannot move more heat than the weakest useful limit:")
    a("")
    a("| rank | location | limit kJ/tick | kW_SI | why |")
    a("|---:|---|---:|---:|---|")
    rows_b = []
    for s in rec["stages"]:
        rows_b.append(
            (
                s["stage_limit_kj_tick"],
                s["tag"],
                s["stage_bottleneck"],
                s["stage_limit_kj_tick"],
                kj_tick_to_kw_si(s["stage_limit_kj_tick"]),
            )
        )
    # also show raw liquid feeds
    for sym, label in (("N2", "S3 N2 liquid feed raw latent"), ("CH4", "S2 CH4 liquid feed raw latent"), ("X", "S1 X liquid feed raw latent")):
        q = GASES[sym].q_latent_kj_tick()
        rows_b.append((q, label, "liquid_feed_latent", q, kj_tick_to_kw_si(q)))
    q_hx5 = chamber_hx_kj_tick(5.0, 300, 300)
    rows_b.append((q_hx5, "any chamber HX @ 5 K, 1 atm", "area 15 m2", q_hx5, kj_tick_to_kw_si(q_hx5)))
    q_rad = rad_kj_tick(15.0, 300, 101.325)
    rows_b.append((q_rad, "ONE convection radiator @ 15 K", "not limiting (N free)", q_rad, kj_tick_to_kw_si(q_rad)))
    rows_b.sort(key=lambda t: t[0])
    for i, (_, loc, kind, q, kw) in enumerate(rows_b, 1):
        a(f"| {i} | {loc} | {q:.3f} | {kw:.2f} | {kind} |")
    a("")
    a("**Practical bottleneck: S3 nitrogen liquid feed (~3.6 kJ/tick latent, ~3.2 kJ/tick after CFHE).**")
    a("Pollutant and methane can each move more heat than nitrogen, so extra S1/S2 chambers do nothing until you parallel **S3 evaporators** (or build a room-scale evaporator with a real liquid pump).")
    a("")
    a("Radiators are **not** the bottleneck. At 15 K over +40 C they are ~0.79 kJ/tick each; ~5 of them dump a single S3's worth of heat; size S1's radiator farm to S1's own ~12 kJ/tick if S1 is used for other loads, or to the chain limit if this cascade is LN2-only.")
    a("")
    a("## 8. Parallel / scale-up")
    a("")
    qn2 = rec["load_q_kj_tick"]
    a(f"- 1x S3 N2 pair: **{qn2:.2f} kJ/tick** cold at -185 C.")
    a(f"- To match 1x S1 pollutant (~{cascades['C_three_stage_X_CH4_N2']['stages'][0]['q_useful_kj_tick']:.1f} kJ/tick) you need about "
      f"**{math.ceil(cascades['C_three_stage_X_CH4_N2']['stages'][0]['q_useful_kj_tick'] / qn2)}x** S3 N2 pairs.")
    a("- Room-scale evaporator (1x1x1 + active vent + liquid pump) removes the 0.25 L/tick cap; then chamber HX area or custom HX becomes the limit.")
    a("")
    a("## 9. Build notes that eat throughput if ignored")
    a("")
    a("1. **CFHE flow match.** Wiki: unmatched mol/tick destroys the temperature swap. Put volume pumps / regulators so liquid mass-flow ≈ vapor mass-flow.")
    a("2. **Evaporator liquid inventory.** Device targets 20 L. Below that, evaporation rate drops (RA2lover).")
    a("3. **Do not set cryo evaporator to 0 kPa** if it puts you under min-condensation (6.3 kPa for N2/CH4) — rate collapses and you risk freeze.")
    a("4. **Coupling-loop pressure ≥ 1 atm** or HX derates linearly. At -180 C that **cannot** be N2/O2/CH4 at 150 kPa without condensing — use **hydrogen** on the cold bus.")
    a("5. **Pollutant coupling** between S1 and S2 is fine at 300 kPa / -90 C (X P_sat is ~2 MPa there).")
    a("6. **Purge valve** on liquid lines between chambers to dump flash gas, or the liquid pipe hits 6 MPa.")
    a("7. **Insulate** everything below 0 C. Pipe convection to a warm room will steal the cascade.")
    a("8. Silanol option D is strictly better as stage 1 (wider window, 15.625 kJ/tick latent) but is late-game / trader.")
    a("")
    a("## 10. Sources")
    a("")
    a("- https://stationeers-wiki.com/Gas")
    a("- https://stationeers-wiki.com/Phase_Change_guide")
    a("- https://stationeers-wiki.com/Phase_Change_Mechanics")
    a("- https://stationeers-wiki.com/Condensation_Chamber")
    a("- https://stationeers-wiki.com/Evaporation_Chamber")
    a("- https://stationeers-wiki.com/Silanol")
    a("- https://stationeers-wiki.com/Thermal_Convection_and_Radiation_Values")
    a("- https://stationeers-wiki.com/Kit_(Counterflow_Heat_Exchanger)")
    a("- https://github.com/Niilo007/Stationeers-Research/wiki/Physics")
    a("- https://github.com/Niilo007/Stationeers-Research/wiki/Gasses")
    a("- RA2lover sandbox notes (evap 0.25 L/tick, 20 L target, 15 m2, CFHE 48 x 15.625 W)")
    a("- Community chart: Gasses-2026-04-19.png (Hydrogen/CH4 split, Alcohol, Silanol, Ozone)")
    a("")

    (OUT / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    schema = """Stationeers cascade AC  —  +40 C dump  →  -180 C / LN2
=====================================================

Recommended: 3 stages   Pollutant (X)  →  Methane (CH4)  →  Nitrogen (N2)

                    +40 C ROOM  (≥1 atm)
                         │
                         │  convection radiators on ONE gas pipe
                         │  dump gas X or N2O @ ~300 kPa, pipe ~55 C
                         ▼
                 ┌───────────────┐
                 │ S1 CONDENSER  │  X   ~70 C   ~3.8 MPa
                 │  (phase chg)  │  HX port ← dump pipe
                 └───────┬───────┘
                         │ X vapor (warm)
                    CFHE x2 (counterflow)
                         │ X liquid (pre-cooled)
                 ┌───────▼───────┐
                 │ S1 EVAPORATOR │  X   ~-93 C  ~1.9 MPa
                 └───────┬───────┘
                         │ coupling gas X @ 300 kPa
                         ▼
                 ┌───────────────┐
                 │ S2 CONDENSER  │  CH4  ~-83 C  ~4.7 MPa
                 └───────┬───────┘
                    CFHE x2
                 ┌───────▼───────┐
                 │ S2 EVAPORATOR │  CH4  ~-145 C
                 └───────┬───────┘
                         │ coupling N2 or H2 ≥ 200 kPa
                         ▼
                 ┌───────────────┐
                 │ S3 CONDENSER  │  N2   ~-135 C     << LN2 tap (liquid out)
                 └───────┬───────┘
                    CFHE x3
                 ┌───────▼───────┐
                 │ S3 EVAPORATOR │  N2   ~-185 C
                 └───────┬───────┘
                         │ cold bus: H2 ≥ 150 kPa
                         ▼
                    LOAD  -180 C
              (or extra N2 product condenser)

Bottleneck (1 chamber each): S3 N2 liquid feed 3.39 kJ/tick = 6.78 kW_SI
Dump radiators: ~5 for LN2-only chain heat, ~13 if S1 is loaded to its own rating.
"""
    (OUT / "SCHEMA.txt").write_text(schema, encoding="utf-8")
    print("wrote", OUT / "cascade_numbers.json")
    print("wrote", OUT / "RESULTS.md")
    print("wrote", OUT / "SCHEMA.txt")
    rec = cascades["C_three_stage_X_CH4_N2"]
    print("recommended load", rec["load_q_kj_tick"], "kJ/tick")
    print("chain bottleneck", rec["chain_bottleneck_stage"], rec["chain_bottleneck_kind"], rec["chain_limit_kj_tick"])


if __name__ == "__main__":
    main()
