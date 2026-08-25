"""Fill unlocked knobs. Discrete search only — step.evaluate never searches."""

from __future__ import annotations

from cascade.constants import (
    DEFAULT_HX_LOOP_KPA,
    DEFAULT_LIQUID_PIPE_L,
    MARGIN_K,
    MAX_CFHE,
    P_MAX_LIQUID_KPA,
)
from cascade.gases import Gas, get_gas
from cascade.models import StepResolved, StepSpec
from cascade.physics import q_chamber_hx_kj_tick, q_feed_kj_tick, ua_chamber_kj_tick_k
from cascade.step import evaluate_step, operable_window, resolved_from_temps


def _locked_map(spec: StepSpec) -> dict[str, bool]:
    return {
        "p_cond_kPa": spec.p_cond_kPa is not None,
        "p_evap_kPa": spec.p_evap_kPa is not None,
        "n_cfhe": spec.n_cfhe is not None,
        "inventory_mol": spec.inventory_mol is not None,
        "n_evap_chambers": spec.n_evap_chambers is not None,
        "n_cond_chambers": spec.n_cond_chambers is not None,
        "hx_hot_kPa": spec.hx_hot_kPa is not None,
        "hx_cold_kPa": spec.hx_cold_kPa is not None,
        "liquid_pipe_L": spec.liquid_pipe_L is not None,
    }


def _defaults(spec: StepSpec) -> tuple[int, int, float, float, float, float | None]:
    n_evap = spec.n_evap_chambers if spec.n_evap_chambers is not None else 1
    n_cond = spec.n_cond_chambers if spec.n_cond_chambers is not None else 1
    hx_hot = spec.hx_hot_kPa if spec.hx_hot_kPa is not None else DEFAULT_HX_LOOP_KPA
    hx_cold = spec.hx_cold_kPa if spec.hx_cold_kPa is not None else DEFAULT_HX_LOOP_KPA
    pipe = spec.liquid_pipe_L if spec.liquid_pipe_L is not None else DEFAULT_LIQUID_PIPE_L
    return n_evap, n_cond, hx_hot, hx_cold, pipe, spec.inventory_mol


def _grid(lo: float, hi: float, step: float) -> list[float]:
    if hi < lo:
        return []
    out = []
    t = lo
    while t <= hi + 1e-9:
        out.append(t)
        t += step
    if out[-1] < hi - 0.01:
        out.append(hi)
    return out


def _q_of(
    gas: Gas,
    t_cond: float,
    t_evap: float,
    n_cfhe: int,
    n_evap: int,
    n_cond: int,
    hx_hot: float,
    hx_cold: float,
    t_hot: float,
    t_cold: float,
) -> float:
    p_cond = gas.p_sat(t_cond)
    p_evap = gas.p_sat(t_evap)
    if p_cond > P_MAX_LIQUID_KPA + 1:
        return -1.0
    q_feed = q_feed_kj_tick(gas, t_cond, t_evap, n_cfhe, n_evap)
    q_evap = q_chamber_hx_kj_tick(t_cold - t_evap, hx_cold, p_evap, n_evap)
    q_cond = q_chamber_hx_kj_tick(t_cond - t_hot, hx_hot, p_cond, n_cond)
    return min(q_feed, q_evap, q_cond)


def optimize_step(spec: StepSpec, t_hot_K: float, t_cold_K: float) -> StepResolved:
    """Max Q at (T_hot, T_cold). Locked fields are never rewritten."""
    gas = get_gas(spec.media)
    locked = _locked_map(spec)
    n_evap, n_cond, hx_hot, hx_cold, pipe, inv = _defaults(spec)
    window = operable_window(gas)

    def pack(tc: float, te: float, n: int) -> StepResolved:
        return resolved_from_temps(
            spec, gas, tc, te, n, n_evap, n_cond, hx_hot, hx_cold, pipe, inv, locked
        )

    if window is None or not gas.can_refrigerate():
        # Still emit a resolved object so evaluate can hard-fail with a message.
        t_cond = t_hot_K + MARGIN_K
        t_evap = t_cold_K - MARGIN_K
        if spec.p_cond_kPa is not None:
            t_cond = gas.t_sat(spec.p_cond_kPa) if gas.t_crit else t_cond
        if spec.p_evap_kPa is not None:
            t_evap = gas.t_sat(spec.p_evap_kPa) if gas.t_freeze else t_evap
        n = spec.n_cfhe if spec.n_cfhe is not None else 1
        return pack(t_cond, t_evap, n)

    t_lo, t_hi = window
    if spec.p_cond_kPa is not None:
        t_conds = [gas.t_sat(spec.p_cond_kPa)]
    else:
        t_conds = _grid(max(t_lo, t_hot_K + 1.0), t_hi, 4.0)
    if spec.p_evap_kPa is not None:
        t_evaps = [gas.t_sat(spec.p_evap_kPa)]
    else:
        t_evaps = _grid(t_lo, min(t_hi, t_cold_K - 1.0), 4.0)
    n_range = [spec.n_cfhe] if spec.n_cfhe is not None else list(range(1, MAX_CFHE + 1))

    best: tuple[float, int, float, float] | None = None  # Q, -n_cfhe, t_cond, t_evap
    for n in n_range:
        for te in t_evaps:
            for tc in t_conds:
                if tc <= t_hot_K or te >= t_cold_K or tc <= te:
                    continue
                q = _q_of(gas, tc, te, n, n_evap, n_cond, hx_hot, hx_cold, t_hot_K, t_cold_K)
                key = (q, -n, tc, te)
                if best is None or key > best:
                    best = key

    # 1 K refine around coarse winner (unlocked axes only)
    if best is not None and (spec.p_cond_kPa is None or spec.p_evap_kPa is None):
        _, _, tc0, te0 = best
        t_conds_r = (
            [tc0]
            if spec.p_cond_kPa is not None
            else _grid(max(t_lo, tc0 - 4), min(t_hi, tc0 + 4), 1.0)
        )
        t_evaps_r = (
            [te0]
            if spec.p_evap_kPa is not None
            else _grid(max(t_lo, te0 - 4), min(t_hi, te0 + 4), 1.0)
        )
        for n in n_range:
            for te in t_evaps_r:
                for tc in t_conds_r:
                    if tc <= t_hot_K or te >= t_cold_K or tc <= te:
                        continue
                    q = _q_of(gas, tc, te, n, n_evap, n_cond, hx_hot, hx_cold, t_hot_K, t_cold_K)
                    key = (q, -n, tc, te)
                    if key > best:
                        best = key

    if best is None:
        n = spec.n_cfhe if spec.n_cfhe is not None else 1
        tc = t_conds[0] if t_conds else t_hot_K + MARGIN_K
        te = t_evaps[0] if t_evaps else t_cold_K - MARGIN_K
        return pack(tc, te, n)

    q, nneg, tc, te = best
    return pack(tc, te, int(-nneg))


def placement_max_t_hot(spec: StepSpec, t_cold_K: float, q_need: float) -> StepResolved | None:
    """Among configs that deliver q_need at T_cold, pick the one that tolerates the warmest T_hot."""
    gas = get_gas(spec.media)
    if not gas.can_refrigerate() or operable_window(gas) is None:
        return None
    locked = _locked_map(spec)
    n_evap, n_cond, hx_hot, hx_cold, pipe, inv = _defaults(spec)
    t_lo, t_hi = operable_window(gas)  # type: ignore[misc]

    if spec.p_cond_kPa is not None:
        t_conds = [gas.t_sat(spec.p_cond_kPa)]
    else:
        t_conds = _grid(t_lo, t_hi, 4.0)
    if spec.p_evap_kPa is not None:
        t_evaps = [gas.t_sat(spec.p_evap_kPa)]
    else:
        t_evaps = _grid(t_lo, min(t_hi, t_cold_K - 0.5), 4.0)
    n_range = [spec.n_cfhe] if spec.n_cfhe is not None else list(range(1, MAX_CFHE + 1))

    best: tuple[float, float, int, float, float] | None = None  # t_hot, q, -n, tc, te
    for n in n_range:
        for te in t_evaps:
            p_evap = gas.p_sat(te)
            q_evap = q_chamber_hx_kj_tick(t_cold_K - te, hx_cold, p_evap, n_evap)
            if q_evap + 1e-9 < q_need:
                continue
            for tc in t_conds:
                if tc <= te:
                    continue
                p_cond = gas.p_sat(tc)
                if p_cond > P_MAX_LIQUID_KPA + 1:
                    continue
                q_feed = q_feed_kj_tick(gas, tc, te, n, n_evap)
                if q_feed + 1e-9 < q_need:
                    continue
                ua_c = ua_chamber_kj_tick_k(hx_hot, p_cond, n_cond)
                if ua_c <= 1e-12:
                    continue
                t_hot = tc - q_need / ua_c
                if t_hot >= tc:
                    continue
                q_actual = min(q_feed, q_evap, q_need + ua_c * max(0.0, tc - t_hot))
                key = (t_hot, q_actual, -n, tc, te)
                if best is None or key > best:
                    best = key
    if best is None:
        return None
    t_hot, _, nneg, tc, te = best
    r = resolved_from_temps(
        spec, gas, tc, te, int(-nneg), n_evap, n_cond, hx_hot, hx_cold, pipe, inv, locked
    )
    ev = evaluate_step(r, t_hot, t_cold_K)
    if ev.q_kj_tick + 1e-6 < q_need or not ev.operable:
        return None
    return r


def placement_fixed_ports(spec: StepSpec, t_hot_K: float, t_cold_K: float, q_need: float) -> StepResolved | None:
    """Any (prefer max-Q) placement that carries q_need between fixed ports."""
    r = optimize_step(spec, t_hot_K, t_cold_K)
    ev = evaluate_step(r, t_hot_K, t_cold_K)
    if ev.operable and ev.q_kj_tick + 1e-6 >= q_need:
        return r
    return None
