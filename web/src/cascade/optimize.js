/** Fill unlocked knobs. Discrete search only — step.evaluate never searches. */

import {
  DEFAULT_HX_LOOP_KPA,
  DEFAULT_LIQUID_PIPE_L,
  MARGIN_K,
  MAX_CFHE,
  P_MAX_LIQUID_KPA,
} from "./constants.js";
import { get_gas } from "./gases.js";
import { k_from_c, q_chamber_hx_kj_tick, q_feed_kj_tick, ua_chamber_kj_tick_k } from "./physics.js";
import { evaluate_step, operable_window, resolved_from_temps } from "./step.js";

function lockedMap(spec) {
  const tCond = spec.t_cond_C != null;
  const tEvap = spec.t_evap_C != null;
  return {
    p_cond_kPa: spec.p_cond_kPa != null && !tCond,
    p_evap_kPa: spec.p_evap_kPa != null && !tEvap,
    t_cond_C: tCond,
    t_evap_C: tEvap,
    t_hot_C: spec.t_hot_C != null,
    t_cold_C: spec.t_cold_C != null,
    n_cfhe: spec.n_cfhe != null,
    inventory_mol: spec.inventory_mol != null,
    n_evap_chambers: spec.n_evap_chambers != null,
    n_cond_chambers: spec.n_cond_chambers != null,
    hx_hot_kPa: spec.hx_hot_kPa != null,
    hx_cold_kPa: spec.hx_cold_kPa != null,
    liquid_pipe_L: spec.liquid_pipe_L != null,
  };
}

function lockedTCond(spec, gas) {
  if (spec.t_cond_C != null) return k_from_c(spec.t_cond_C);
  if (spec.p_cond_kPa != null && gas.t_crit != null) return gas.t_sat(spec.p_cond_kPa);
  return null;
}

function lockedTEvap(spec, gas) {
  if (spec.t_evap_C != null) return k_from_c(spec.t_evap_C);
  if (spec.p_evap_kPa != null && gas.t_freeze != null) return gas.t_sat(spec.p_evap_kPa);
  return null;
}

function defaults(spec) {
  const n_evap = spec.n_evap_chambers != null ? spec.n_evap_chambers : 1;
  const n_cond = spec.n_cond_chambers != null ? spec.n_cond_chambers : 1;
  const hx_hot = spec.hx_hot_kPa != null ? spec.hx_hot_kPa : DEFAULT_HX_LOOP_KPA;
  const hx_cold = spec.hx_cold_kPa != null ? spec.hx_cold_kPa : DEFAULT_HX_LOOP_KPA;
  const pipe = spec.liquid_pipe_L != null ? spec.liquid_pipe_L : DEFAULT_LIQUID_PIPE_L;
  return [n_evap, n_cond, hx_hot, hx_cold, pipe, spec.inventory_mol];
}

function grid(lo, hi, step) {
  if (hi < lo) return [];
  const out = [];
  let t = lo;
  while (t <= hi + 1e-9) {
    out.push(t);
    t += step;
  }
  if (out[out.length - 1] < hi - 0.01) out.push(hi);
  return out;
}

/** Python tuple comparison: first differing element wins. */
function keyGt(a, b) {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    if (a[i] > b[i]) return true;
    if (a[i] < b[i]) return false;
  }
  return a.length > b.length;
}

function qOf(gas, t_cond, t_evap, n_cfhe, n_evap, n_cond, hx_hot, hx_cold, t_hot, t_cold) {
  const p_cond = gas.p_sat(t_cond);
  const p_evap = gas.p_sat(t_evap);
  if (p_cond > P_MAX_LIQUID_KPA + 1) return -1.0;
  const q_feed = q_feed_kj_tick(gas, t_cond, t_evap, n_cfhe, n_evap);
  const q_evap = q_chamber_hx_kj_tick(t_cold - t_evap, hx_cold, p_evap, n_evap);
  const q_cond = q_chamber_hx_kj_tick(t_cond - t_hot, hx_hot, p_cond, n_cond);
  return Math.min(q_feed, q_evap, q_cond);
}

export function optimize_step(spec, t_hot_K, t_cold_K) {
  const gas = get_gas(spec.media);
  const locked = lockedMap(spec);
  const [n_evap, n_cond, hx_hot, hx_cold, pipe, inv] = defaults(spec);
  const window = operable_window(gas);

  const pack = (tc, te, n) =>
    resolved_from_temps(spec, gas, tc, te, n, n_evap, n_cond, hx_hot, hx_cold, pipe, inv, locked);

  if (window == null || !gas.can_refrigerate()) {
    let t_cond = t_hot_K + MARGIN_K;
    let t_evap = t_cold_K - MARGIN_K;
    const locked_tc = lockedTCond(spec, gas);
    const locked_te = lockedTEvap(spec, gas);
    if (locked_tc != null) t_cond = locked_tc;
    if (locked_te != null) t_evap = locked_te;
    const n = spec.n_cfhe != null ? spec.n_cfhe : 1;
    return pack(t_cond, t_evap, n);
  }

  const [t_lo, t_hi] = window;
  const locked_tc = lockedTCond(spec, gas);
  const locked_te = lockedTEvap(spec, gas);
  const t_conds = locked_tc != null ? [locked_tc] : grid(Math.max(t_lo, t_hot_K + 1.0), t_hi, 4.0);
  const t_evaps = locked_te != null ? [locked_te] : grid(t_lo, Math.min(t_hi, t_cold_K - 1.0), 4.0);
  const n_range = spec.n_cfhe != null ? [spec.n_cfhe] : Array.from({ length: MAX_CFHE }, (_, i) => i + 1);

  /** @type {number[] | null} */
  let best = null;
  for (const n of n_range) {
    for (const te of t_evaps) {
      for (const tc of t_conds) {
        if (tc <= t_hot_K || te >= t_cold_K || tc <= te) continue;
        const q = qOf(gas, tc, te, n, n_evap, n_cond, hx_hot, hx_cold, t_hot_K, t_cold_K);
        const key = [q, -n, tc, te];
        if (best == null || keyGt(key, best)) best = key;
      }
    }
  }

  if (best != null && (locked_tc == null || locked_te == null)) {
    const [, , tc0, te0] = best;
    const t_conds_r = locked_tc != null ? [tc0] : grid(Math.max(t_lo, tc0 - 4), Math.min(t_hi, tc0 + 4), 1.0);
    const t_evaps_r = locked_te != null ? [te0] : grid(Math.max(t_lo, te0 - 4), Math.min(t_hi, te0 + 4), 1.0);
    for (const n of n_range) {
      for (const te of t_evaps_r) {
        for (const tc of t_conds_r) {
          if (tc <= t_hot_K || te >= t_cold_K || tc <= te) continue;
          const q = qOf(gas, tc, te, n, n_evap, n_cond, hx_hot, hx_cold, t_hot_K, t_cold_K);
          const key = [q, -n, tc, te];
          if (keyGt(key, best)) best = key;
        }
      }
    }
  }

  if (best == null) {
    const n = spec.n_cfhe != null ? spec.n_cfhe : 1;
    const tc = t_conds.length ? t_conds[0] : t_hot_K + MARGIN_K;
    const te = t_evaps.length ? t_evaps[0] : t_cold_K - MARGIN_K;
    return pack(tc, te, n);
  }

  const [, nneg, tc, te] = best;
  return pack(tc, te, -nneg);
}

export function placement_max_t_hot(spec, t_cold_K, q_need, t_hot_cap = null) {
  const gas = get_gas(spec.media);
  if (!gas.can_refrigerate() || operable_window(gas) == null) return null;
  const locked = lockedMap(spec);
  const [n_evap, n_cond, hx_hot, hx_cold, pipe, inv] = defaults(spec);
  const [t_lo, t_hi] = operable_window(gas);

  const locked_tc = lockedTCond(spec, gas);
  const locked_te = lockedTEvap(spec, gas);
  const t_conds = locked_tc != null ? [locked_tc] : grid(t_lo, t_hi, 4.0);
  const t_evaps =
    locked_te != null ? [locked_te] : grid(t_lo, Math.min(t_hi, t_cold_K - 0.5), 4.0);
  const n_range = spec.n_cfhe != null ? [spec.n_cfhe] : Array.from({ length: MAX_CFHE }, (_, i) => i + 1);

  /** @type {number[] | null} */
  let best = null;
  for (const n of n_range) {
    for (const te of t_evaps) {
      const p_evap = gas.p_sat(te);
      const q_evap = q_chamber_hx_kj_tick(t_cold_K - te, hx_cold, p_evap, n_evap);
      if (q_evap + 1e-9 < q_need) continue;
      for (const tc of t_conds) {
        if (tc <= te) continue;
        const p_cond = gas.p_sat(tc);
        if (p_cond > P_MAX_LIQUID_KPA + 1) continue;
        const q_feed = q_feed_kj_tick(gas, tc, te, n, n_evap);
        if (q_feed + 1e-9 < q_need) continue;
        const ua_c = ua_chamber_kj_tick_k(hx_hot, p_cond, n_cond);
        if (ua_c <= 1e-12) continue;
        const t_hot = tc - q_need / ua_c;
        if (t_hot >= tc) continue;
        const q_actual = Math.min(q_feed, q_evap, q_need + ua_c * Math.max(0.0, tc - t_hot));
        const excess = t_hot_cap == null ? 0.0 : Math.max(0.0, t_hot - t_hot_cap);
        const key = [-excess, t_hot, q_actual, -n, tc, te];
        if (best == null || keyGt(key, best)) best = key;
      }
    }
  }
  if (best == null) return null;
  const [, t_hot, , nneg, tc, te] = best;
  const r = resolved_from_temps(
    spec,
    gas,
    tc,
    te,
    -nneg,
    n_evap,
    n_cond,
    hx_hot,
    hx_cold,
    pipe,
    inv,
    locked,
  );
  const ev = evaluate_step(r, t_hot, t_cold_K);
  if (ev.q_kj_tick + 1e-6 < q_need || !ev.operable) return null;
  return r;
}

export function placement_fixed_ports(spec, t_hot_K, t_cold_K, q_need) {
  const r = optimize_step(spec, t_hot_K, t_cold_K);
  const ev = evaluate_step(r, t_hot_K, t_cold_K);
  if (ev.operable && ev.q_kj_tick + 1e-6 >= q_need) return r;
  return null;
}
