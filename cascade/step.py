"""Evaluate one evaporator–condenser step. No search."""

from __future__ import annotations

from cascade.constants import (
    CHAMBER_VOLUME_L,
    EVAP_TARGET_L,
    LIQUID_PIPE_FILL_MAX,
    MARGIN_K,
    P_MAX_LIQUID_KPA,
    TIGHT_MARGIN_K,
)
from cascade.gases import Gas, get_gas
from cascade.models import (
    Bottleneck,
    InventoryBand,
    PowerCurve,
    StepEval,
    StepResolved,
    Warning,
)
from cascade.physics import (
    n_gas_ideal,
    q_chamber_hx_kj_tick,
    q_feed_kj_tick,
    ua_chamber_kj_tick_k,
    useful_frac,
)


_LEVER = {
    "liquid_feed": "Add a parallel evaporation chamber (or a room-scale evaporator with a real liquid pump).",
    "evap_HX": "Lower evaporator pressure (more dT) if freeze allows, raise cold-HX loop pressure to >=1 atm, or add an evaporator chamber.",
    "cond_HX": "Raise condenser pressure (more dT) if T_crit allows, raise hot-HX loop pressure to >=1 atm, add a condenser chamber, or add dump radiators.",
    "cfhe": "Add another counterflow heat exchanger (daisy-chain) to recover inlet-liquid sensible heat.",
    "coupling": "This media cannot couple here - change refrigerant or add a stage. Pressure will not open the freeze/crit window.",
    "dump_radiators": "Add pipe convection radiators on the dump loop (or raise dump-loop dT).",
    "none": "No heat is moving; fix hard-fail warnings first.",
}


def _inventory_band(gas: Gas, resolved: StepResolved) -> InventoryBand:
    pipe = resolved.liquid_pipe_L
    if not gas.v_liq:
        return InventoryBand(0.0, 0.0, "missing V_liq - cannot size inventory", resolved.inventory_mol, None)
    n_liq_evap = EVAP_TARGET_L / gas.v_liq
    n_gas = n_gas_ideal(resolved.p_evap_kPa, resolved.t_evap_K, CHAMBER_VOLUME_L)
    n_min = n_liq_evap + n_gas
    n_pipe_max = (pipe * LIQUID_PIPE_FILL_MAX) / gas.v_liq
    n_max = n_liq_evap + n_pipe_max
    chosen = resolved.inventory_mol
    in_band = None if chosen is None else (n_min <= chosen <= n_max)
    note = (
        f"Keep about {n_min:.0f}-{n_max:.0f} mol of {gas.symbol}: "
        f">={n_min:.0f} mol holds 20 L in the evaporator plus chamber vapor; "
        f"<={n_max:.0f} mol stays under {LIQUID_PIPE_FILL_MAX*100:.0f}% of a {pipe:.0f} L liquid pipe. "
        "Inventory does not change Q once 20 L is held."
    )
    return InventoryBand(round(n_min, 2), round(n_max, 2), note, chosen, in_band)


def _hard(code: str, msg: str, step: int | None = None) -> Warning:
    return Warning("hard", code, msg, step)


def _soft(code: str, msg: str, step: int | None = None) -> Warning:
    return Warning("soft", code, msg, step)


def warnings_for(
    gas: Gas,
    resolved: StepResolved,
    t_hot_K: float,
    t_cold_K: float,
    uf: float,
    step: int | None = None,
) -> list[Warning]:
    w: list[Warning] = []
    if not gas.can_refrigerate():
        w.append(_hard("missing_props", f"{gas.symbol} is missing L / V_liq / freeze / crit - cannot refrigerate.", step))
        return w
    assert gas.t_freeze is not None and gas.t_crit is not None and gas.p_min_cond is not None
    if resolved.t_evap_K < gas.t_freeze:
        w.append(_hard("freeze", f"T_evap {resolved.t_evap_K-273.15:.1f} C is below freeze {gas.t_freeze-273.15:.1f} C.", step))
    if resolved.t_cond_K > gas.t_crit:
        w.append(_hard("crit", f"T_cond {resolved.t_cond_K-273.15:.1f} C is above T_crit {gas.t_crit-273.15:.1f} C.", step))
    if resolved.t_cond_K <= t_hot_K:
        w.append(_hard("cannot_dump", f"T_cond {resolved.t_cond_K-273.15:.1f} C is not hotter than the hot sink {t_hot_K-273.15:.1f} C.", step))
    if resolved.t_evap_K >= t_cold_K:
        w.append(_hard("cannot_absorb", f"T_evap {resolved.t_evap_K-273.15:.1f} C is not colder than the load {t_cold_K-273.15:.1f} C.", step))
    if uf <= 0:
        w.append(_hard("useful_frac", "CFHE residual sensible load exceeds latent heat - add CFHEs or shrink the T span.", step))
    if resolved.p_cond_kPa > P_MAX_LIQUID_KPA + 1:
        w.append(_hard("overpressure", f"P_cond {resolved.p_cond_kPa:.0f} kPa exceeds 6 MPa liquid-pipe limit.", step))
    if resolved.p_evap_kPa + 0.05 < gas.p_min_cond:
        w.append(_hard("below_min_cond", f"P_evap {resolved.p_evap_kPa:.1f} kPa is below min condensation {gas.p_min_cond:.1f} kPa.", step))
    if resolved.p_evap_kPa > P_MAX_LIQUID_KPA + 1:
        w.append(_hard("overpressure", f"P_evap {resolved.p_evap_kPa:.0f} kPa exceeds 6 MPa.", step))
    if resolved.t_evap_K >= gas.t_freeze and (resolved.t_evap_K - gas.t_freeze) < TIGHT_MARGIN_K:
        w.append(_soft("tight_freeze", f"Only {resolved.t_evap_K - gas.t_freeze:.1f} K above freeze.", step))
    if resolved.t_cond_K <= gas.t_crit and (gas.t_crit - resolved.t_cond_K) < TIGHT_MARGIN_K:
        w.append(_soft("tight_crit", f"Only {gas.t_crit - resolved.t_cond_K:.1f} K below T_crit.", step))
    if resolved.hx_hot_kPa < 101.325:
        w.append(_soft("hx_hot_derate", f"Hot HX loop {resolved.hx_hot_kPa:.0f} kPa < 1 atm - chamber HX derates.", step))
    if resolved.hx_cold_kPa < 101.325:
        w.append(_soft("hx_cold_derate", f"Cold HX loop {resolved.hx_cold_kPa:.0f} kPa < 1 atm - chamber HX derates.", step))
    if resolved.p_evap_kPa < 101.325:
        w.append(_soft("p_evap_derate", f"Evaporator {resolved.p_evap_kPa:.0f} kPa < 1 atm - chamber HX derates.", step))
    if gas.shc is None:
        w.append(_soft("missing_shc", f"{gas.symbol} has no SHC; CFHE parasitic treated as 0.", step))
    if gas.shc and gas.latent:
        span_ratio = gas.shc * max(0.0, resolved.t_cond_K - resolved.t_evap_K) / gas.latent
        if span_ratio > 1.5 and resolved.n_cfhe < 3:
            w.append(_soft("cfhe_span", f"c_p*dT/L = {span_ratio:.2f}; few CFHEs will eat most of the latent heat.", step))
    return w


def _bottleneck(q_feed: float, q_evap: float, q_cond: float, uf: float, q: float) -> Bottleneck:
    if q <= 0:
        kind: str = "none"
    else:
        parts = [("liquid_feed", q_feed), ("evap_HX", q_evap), ("cond_HX", q_cond)]
        kind = min(parts, key=lambda kv: kv[1])[0]
        if kind == "liquid_feed" and uf < 0.85:
            kind = "cfhe"
    return Bottleneck(kind, round(q, 4), _LEVER[kind])  # type: ignore[arg-type]


def power_curve(
    gas: Gas,
    resolved: StepResolved,
    t_hot_K: float,
) -> PowerCurve:
    uf = useful_frac(gas, resolved.t_cond_K, resolved.t_evap_K, resolved.n_cfhe)
    q_feed = q_feed_kj_tick(
        gas, resolved.t_cond_K, resolved.t_evap_K, resolved.n_cfhe, resolved.n_evap_chambers
    )
    q_cond = q_chamber_hx_kj_tick(
        resolved.t_cond_K - t_hot_K,
        resolved.hx_hot_kPa,
        resolved.p_cond_kPa,
        resolved.n_cond_chambers,
    )
    ua_evap = ua_chamber_kj_tick_k(
        resolved.hx_cold_kPa, resolved.p_evap_kPa, resolved.n_evap_chambers
    )
    plateau = min(q_feed, q_cond)
    if q_cond <= q_feed + 1e-12:
        limited = "cond_HX"
    else:
        limited = "liquid_feed"
    if ua_evap <= 1e-12:
        t_break = resolved.t_evap_K
    else:
        t_break = resolved.t_evap_K + plateau / ua_evap
    return PowerCurve(
        t_evap_K=resolved.t_evap_K,
        t_break_K=t_break,
        q_plateau_kj_tick=max(0.0, plateau),
        slope_kj_tick_per_K=ua_evap,
        plateau_limited_by=limited,
    )


def evaluate_step(
    resolved: StepResolved,
    t_hot_K: float,
    t_cold_K: float,
    step: int | None = None,
) -> StepEval:
    gas = get_gas(resolved.media)
    uf = useful_frac(gas, resolved.t_cond_K, resolved.t_evap_K, resolved.n_cfhe)
    q_feed = q_feed_kj_tick(
        gas, resolved.t_cond_K, resolved.t_evap_K, resolved.n_cfhe, resolved.n_evap_chambers
    )
    q_evap = q_chamber_hx_kj_tick(
        t_cold_K - resolved.t_evap_K,
        resolved.hx_cold_kPa,
        resolved.p_evap_kPa,
        resolved.n_evap_chambers,
    )
    q_cond = q_chamber_hx_kj_tick(
        resolved.t_cond_K - t_hot_K,
        resolved.hx_hot_kPa,
        resolved.p_cond_kPa,
        resolved.n_cond_chambers,
    )
    warns = warnings_for(gas, resolved, t_hot_K, t_cold_K, uf, step)
    hard = any(w.severity == "hard" for w in warns)
    q = 0.0 if hard else min(q_feed, q_evap, q_cond)
    band = _inventory_band(gas, resolved)
    if band.in_band is False:
        warns.append(
            _soft(
                "inventory",
                f"Chosen {band.chosen_mol:.0f} mol is outside {band.mol_min:.0f}-{band.mol_max:.0f} mol.",
                step,
            )
        )
    curve = power_curve(gas, resolved, t_hot_K)
    if hard:
        curve = PowerCurve(resolved.t_evap_K, resolved.t_evap_K, 0.0, 0.0, "none")
    bot = _bottleneck(q_feed, q_evap, q_cond, uf, q)
    bot.step = step
    return StepEval(
        resolved=resolved,
        t_hot_K=t_hot_K,
        t_cold_K=t_cold_K,
        q_feed=round(q_feed, 4),
        q_evap_hx=round(q_evap, 4),
        q_cond_hx=round(q_cond, 4),
        q_kj_tick=round(q, 4),
        useful_frac=round(uf, 4),
        warnings=warns,
        bottleneck=bot,
        curve=curve,
        inventory=band,
    )


def resolved_from_temps(
    spec: "object",
    gas: Gas,
    t_cond_K: float,
    t_evap_K: float,
    n_cfhe: int,
    n_evap: int,
    n_cond: int,
    hx_hot: float,
    hx_cold: float,
    liquid_pipe_L: float,
    inventory_mol: float | None,
    locked: dict[str, bool],
) -> StepResolved:
    return StepResolved(
        media=gas.symbol,
        t_cond_K=t_cond_K,
        t_evap_K=t_evap_K,
        p_cond_kPa=gas.p_sat(t_cond_K),
        p_evap_kPa=gas.p_sat(t_evap_K),
        n_cfhe=n_cfhe,
        n_evap_chambers=n_evap,
        n_cond_chambers=n_cond,
        hx_hot_kPa=hx_hot,
        hx_cold_kPa=hx_cold,
        liquid_pipe_L=liquid_pipe_L,
        inventory_mol=inventory_mol,
        locked=locked,
    )


def operable_window(gas: Gas) -> tuple[float, float] | None:
    if gas.t_freeze is None or gas.t_crit is None:
        return None
    lo = gas.t_freeze + MARGIN_K
    hi = gas.t_crit - MARGIN_K
    if lo >= hi:
        return None
    return lo, hi
