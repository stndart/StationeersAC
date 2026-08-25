"""Chain steps: coupling, binary-search Q at target T, dump radiators."""

from __future__ import annotations

import math

from cascade.constants import DUMP_RAD_DT_K, MARGIN_K, P_ATM
from cascade.gases import get_gas
from cascade.models import (
    Bottleneck,
    CascadeResult,
    PowerCurve,
    StepEval,
    StepResolved,
    StepSpec,
    Warning,
)
from cascade.optimize import optimize_step, placement_fixed_ports, placement_max_t_hot
from cascade.physics import c_from_k, k_from_c, kj_tick_to_kj_s, q_radiator_kj_tick
from cascade.step import evaluate_step, operable_window


def _t_hot_for_resolved(resolved: StepResolved, q_need: float) -> float:
    """Warmest T_hot at which condenser HX still delivers q_need."""
    from cascade.physics import ua_chamber_kj_tick_k

    ua = ua_chamber_kj_tick_k(resolved.hx_hot_kPa, resolved.p_cond_kPa, resolved.n_cond_chambers)
    if ua <= 1e-12:
        return resolved.t_cond_K
    return resolved.t_cond_K - q_need / ua


def _try_q(specs: list[StepSpec], t_dump_K: float, t_target_K: float, q_need: float) -> list[tuple[StepResolved, float, float]] | None:
    """Place from load backward. Returns (resolved, T_hot, T_cold) per step or None."""
    n = len(specs)
    placed: list[tuple[StepResolved, float, float] | None] = [None] * n
    t_cold = t_target_K
    for i in range(n - 1, -1, -1):
        spec = specs[i]
        if i == 0:
            r = placement_fixed_ports(spec, t_dump_K, t_cold, q_need)
            if r is None:
                return None
            placed[i] = (r, t_dump_K, t_cold)
        else:
            r = placement_max_t_hot(spec, t_cold, q_need)
            if r is None:
                return None
            t_hot = _t_hot_for_resolved(r, q_need)
            ev = evaluate_step(r, t_hot, t_cold)
            if not ev.operable or ev.q_kj_tick + 1e-6 < q_need:
                return None
            placed[i] = (r, t_hot, t_cold)
            t_cold = t_hot
    return placed  # type: ignore[return-value]


def _max_feed_bound(specs: list[StepSpec]) -> float:
    from cascade.physics import q_feed_kj_tick

    cap = 0.0
    for spec in specs:
        gas = get_gas(spec.media)
        if not gas.can_refrigerate():
            continue
        n_evap = spec.n_evap_chambers or 1
        n_cfhe = spec.n_cfhe or 6
        w = operable_window(gas)
        if w is None:
            continue
        q = q_feed_kj_tick(gas, w[1], w[0], n_cfhe, n_evap)
        cap = max(cap, q)
    return max(cap, 0.5)


def _floor_if_sacrifice(specs: list[StepSpec]) -> float:
    """Last-stage freeze+margin if upstream media can still couple to its condenser."""
    last = get_gas(specs[-1].media)
    if last.t_freeze is None or last.t_crit is None:
        return float("nan")
    floor = last.t_freeze + MARGIN_K
    t_cond_max_next = last.t_crit - MARGIN_K
    for spec in reversed(specs[:-1]):
        gas = get_gas(spec.media)
        w = operable_window(gas)
        if w is None or gas.t_crit is None:
            return float("nan")
        # Warmer evaporator must sit below the colder stage's hottest usable condenser.
        if w[0] >= t_cond_max_next:
            return float("nan")
        t_cond_max_next = gas.t_crit - MARGIN_K
    return floor


def _chain_curve(evals: list[StepEval], t_dump_K: float) -> PowerCurve:
    last = evals[-1]
    upstream = min((e.q_kj_tick for e in evals[:-1]), default=last.curve.q_plateau_kj_tick)
    plateau = min(last.curve.q_plateau_kj_tick, upstream)
    ua = last.curve.slope_kj_tick_per_K
    t_evap = last.resolved.t_evap_K
    t_break = t_evap + plateau / ua if ua > 1e-12 else t_evap
    limited = last.curve.plateau_limited_by
    if upstream + 1e-9 < last.curve.q_plateau_kj_tick:
        limited = "upstream"
    return PowerCurve(t_evap, t_break, plateau, ua, limited)


def run_cascade(
    steps: list[StepSpec],
    t_hot_C: float,
    t_target_C: float,
    dump_radiators: int | None = None,
) -> CascadeResult:
    if not steps:
        raise ValueError("need at least one step")
    t_dump = k_from_c(t_hot_C)
    t_target = k_from_c(t_target_C)
    notes: list[str] = []
    extra_warns: list[Warning] = []

    hi = _max_feed_bound(steps)
    lo = 0.0
    best_place: list[tuple[StepResolved, float, float]] | None = None
    best_q = 0.0
    # binary search on Q
    for _ in range(24):
        mid = (lo + hi) / 2.0
        if mid < 1e-6:
            break
        placed = _try_q(steps, t_dump, t_target, mid)
        if placed is None:
            hi = mid
        else:
            lo = mid
            best_place = placed
            best_q = mid

    if best_place is None:
        # Fall back: independent optimize with equally spaced couplings so we still report why.
        n = len(steps)
        temps = [t_dump + (t_target - t_dump) * i / n for i in range(n + 1)]
        # temps[0]=dump, temps[n]=target. step i: hot=temps[i], cold=temps[i+1]
        evals = []
        for i, spec in enumerate(steps):
            r = optimize_step(spec, temps[i], temps[i + 1])
            ev = evaluate_step(r, temps[i], temps[i + 1], step=i)
            evals.append(ev)
            extra_warns.append(
                Warning("hard", "no_feasible_q", "Could not place a feasible Q for this chain at the target T. Showing an infeasible equal-span guess.", i)
            )
        bot = Bottleneck("coupling", 0.0, "Change media or add a stage - this chain cannot carry heat at the requested target.", 0)
        floor = _floor_if_sacrifice(steps)
        curve = PowerCurve(t_target, t_target, 0.0, 0.0, "none")
        return CascadeResult(
            t_hot_C=t_hot_C,
            t_target_C=t_target_C,
            t_coldest_C=c_from_k(evals[-1].resolved.t_evap_K),
            t_floor_if_sacrifice_C=c_from_k(floor) if floor == floor else float("nan"),
            q_at_target_kj_tick=0.0,
            q_at_target_kj_s=0.0,
            dump_radiators=dump_radiators or 0,
            dump_radiators_locked=dump_radiators is not None,
            steps=evals,
            warnings=extra_warns + [w for e in evals for w in e.warnings],
            bottleneck=bot,
            curve=curve,
            notes=["Optimizer found no operable placement at the target temperature."],
        )

    evals: list[StepEval] = []
    for i, (r, t_hot, t_cold) in enumerate(best_place):
        evals.append(evaluate_step(r, t_hot, t_cold, step=i))

    q_chain = min(e.q_kj_tick for e in evals)
    bot_step = min(range(len(evals)), key=lambda i: evals[i].q_kj_tick)
    bot = evals[bot_step].bottleneck

    rad_q = q_radiator_kj_tick(DUMP_RAD_DT_K, 300.0, P_ATM, 1)
    n_rad_needed = max(1, math.ceil(q_chain / rad_q - 1e-9)) if rad_q > 0 else 1
    rad_locked = dump_radiators is not None
    n_rad = dump_radiators if rad_locked else n_rad_needed
    if rad_locked:
        q_rad = q_radiator_kj_tick(DUMP_RAD_DT_K, 300.0, P_ATM, n_rad)
        if q_rad + 1e-9 < q_chain:
            extra_warns.append(
                Warning(
                    "soft",
                    "dump_undersized",
                    f"{n_rad} dump radiators at {DUMP_RAD_DT_K:.0f} K only dump {q_rad:.2f} kJ/tick; chain wants {q_chain:.2f}.",
                    0,
                )
            )
            if q_rad < bot.q_kj_tick:
                bot = Bottleneck("dump_radiators", round(q_rad, 4), "Add pipe convection radiators on the dump loop.", 0)
                q_chain = q_rad

    notes.append(
        f"Q(T) is a broken stick: plateau {min(e.curve.q_plateau_kj_tick for e in evals):.3f} kJ/tick "
        f"until the load approaches T_evap, then linear in (T_cold - T_evap). Not constant down to T_cond."
    )
    notes.append(
        f"Dump radiators: {n_rad} "
        + ("(locked). " if rad_locked else f"(sized so dump is not the bottleneck at {DUMP_RAD_DT_K:.0f} K over room). ")
        + f"One radiator ~ {rad_q:.3f} kJ/tick at {DUMP_RAD_DT_K:.0f} K, >=1 atm both sides."
    )

    floor = _floor_if_sacrifice(steps)
    if floor == floor:
        notes.append(
            f"If you park the last evaporator at freeze+{MARGIN_K:.0f} K "
            f"({c_from_k(floor):.1f} C) you can go colder than the Q-max design, at lower power."
        )
    else:
        notes.append(
            "Upstream freeze/crit windows cannot couple if the last stage sits at its freeze floor."
        )
    curve = _chain_curve(evals, t_dump)
    all_w = extra_warns + [w for e in evals for w in e.warnings]
    return CascadeResult(
        t_hot_C=t_hot_C,
        t_target_C=t_target_C,
        t_coldest_C=round(c_from_k(evals[-1].resolved.t_evap_K), 2),
        t_floor_if_sacrifice_C=round(c_from_k(floor), 2) if floor == floor else float("nan"),
        q_at_target_kj_tick=round(q_chain, 4),
        q_at_target_kj_s=round(kj_tick_to_kj_s(q_chain), 4),
        dump_radiators=n_rad,
        dump_radiators_locked=rad_locked,
        steps=evals,
        warnings=all_w,
        bottleneck=bot,
        curve=curve,
        notes=notes,
    )
