/** Chain steps: coupling, binary-search Q at target T, dump radiators. */

import { DUMP_RAD_DT_K, MARGIN_K, P_ATM } from "./constants.js";
import { get_gas } from "./gases.js";
import { Bottleneck, CascadeResult, PowerCurve, Warning, round } from "./models.js";
import { optimize_step, placement_fixed_ports, placement_max_t_hot } from "./optimize.js";
import {
  c_from_k,
  k_from_c,
  kj_tick_to_kj_s,
  q_feed_kj_tick,
  q_radiator_kj_tick,
  ua_chamber_kj_tick_k,
} from "./physics.js";
import { evaluate_step, operable_window } from "./step.js";

function tHotForResolved(resolved, q_need) {
  const ua = ua_chamber_kj_tick_k(resolved.hx_hot_kPa, resolved.p_cond_kPa, resolved.n_cond_chambers);
  if (ua <= 1e-12) return resolved.t_cond_K;
  return resolved.t_cond_K - q_need / ua;
}

function tryQ(specs, t_dump_K, t_target_K, q_need) {
  const n = specs.length;
  /** @type {Array<[import("./models.js").StepResolved, number, number] | null>} */
  const placed = Array.from({ length: n }, () => null);
  let t_cold = t_target_K;
  for (let i = n - 1; i >= 0; i--) {
    const spec = specs[i];
    if (i === 0) {
      const r = placement_fixed_ports(spec, t_dump_K, t_cold, q_need);
      if (r == null) return null;
      placed[i] = [r, t_dump_K, t_cold];
    } else {
      const r = placement_max_t_hot(spec, t_cold, q_need);
      if (r == null) return null;
      const t_hot = tHotForResolved(r, q_need);
      const ev = evaluate_step(r, t_hot, t_cold);
      if (!ev.operable || ev.q_kj_tick + 1e-6 < q_need) return null;
      placed[i] = [r, t_hot, t_cold];
      t_cold = t_hot;
    }
  }
  return placed;
}

function maxFeedBound(specs) {
  let cap = 0.0;
  for (const spec of specs) {
    const gas = get_gas(spec.media);
    if (!gas.can_refrigerate()) continue;
    const n_evap = spec.n_evap_chambers || 1;
    const n_cfhe = spec.n_cfhe || 6;
    const w = operable_window(gas);
    if (w == null) continue;
    const q = q_feed_kj_tick(gas, w[1], w[0], n_cfhe, n_evap);
    cap = Math.max(cap, q);
  }
  return Math.max(cap, 0.5);
}

function floorIfSacrifice(specs) {
  const last = get_gas(specs[specs.length - 1].media);
  if (last.t_freeze == null || last.t_crit == null) return Number.NaN;
  const floor = last.t_freeze + MARGIN_K;
  let t_cond_max_next = last.t_crit - MARGIN_K;
  for (let i = specs.length - 2; i >= 0; i--) {
    const spec = specs[i];
    const gas = get_gas(spec.media);
    const w = operable_window(gas);
    if (w == null || gas.t_crit == null) return Number.NaN;
    if (w[0] >= t_cond_max_next) return Number.NaN;
    t_cond_max_next = gas.t_crit - MARGIN_K;
  }
  return floor;
}

function chainCurve(evals, _t_dump_K) {
  const last = evals[evals.length - 1];
  const upstreamQs = evals.slice(0, -1).map((e) => e.q_kj_tick);
  const upstream = upstreamQs.length ? Math.min(...upstreamQs) : last.curve.q_plateau_kj_tick;
  const plateau = Math.min(last.curve.q_plateau_kj_tick, upstream);
  const ua = last.curve.slope_kj_tick_per_K;
  const t_evap = last.resolved.t_evap_K;
  const t_break = ua > 1e-12 ? t_evap + plateau / ua : t_evap;
  let limited = last.curve.plateau_limited_by;
  if (upstream + 1e-9 < last.curve.q_plateau_kj_tick) limited = "upstream";
  return new PowerCurve(t_evap, t_break, plateau, ua, limited);
}

export function run_cascade(steps, t_hot_C, t_target_C, dump_radiators = null) {
  if (!steps.length) throw new Error("need at least one step");
  const t_dump = k_from_c(t_hot_C);
  const t_target = k_from_c(t_target_C);
  const notes = [];
  const extra_warns = [];

  let hi = maxFeedBound(steps);
  let lo = 0.0;
  /** @type {Array<[import("./models.js").StepResolved, number, number]> | null} */
  let best_place = null;
  let best_q = 0.0;
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2.0;
    if (mid < 1e-6) break;
    const placed = tryQ(steps, t_dump, t_target, mid);
    if (placed == null) {
      hi = mid;
    } else {
      lo = mid;
      best_place = placed;
      best_q = mid;
    }
  }

  if (best_place == null) {
    const n = steps.length;
    const temps = Array.from({ length: n + 1 }, (_, i) => t_dump + ((t_target - t_dump) * i) / n);
    const evals = [];
    for (let i = 0; i < n; i++) {
      const spec = steps[i];
      const r = optimize_step(spec, temps[i], temps[i + 1]);
      const ev = evaluate_step(r, temps[i], temps[i + 1], i);
      evals.push(ev);
      extra_warns.push(
        new Warning(
          "hard",
          "no_feasible_q",
          "Could not place a feasible Q for this chain at the target T. Showing an infeasible equal-span guess.",
          i,
        ),
      );
    }
    const bot = new Bottleneck(
      "coupling",
      0.0,
      "Change media or add a stage - this chain cannot carry heat at the requested target.",
      0,
    );
    const floor = floorIfSacrifice(steps);
    const curve = new PowerCurve(t_target, t_target, 0.0, 0.0, "none");
    return new CascadeResult({
      t_hot_C,
      t_target_C,
      t_coldest_C: c_from_k(evals[evals.length - 1].resolved.t_evap_K),
      t_floor_if_sacrifice_C: floor === floor ? c_from_k(floor) : Number.NaN,
      q_at_target_kj_tick: 0.0,
      q_at_target_kj_s: 0.0,
      dump_radiators: dump_radiators || 0,
      dump_radiators_locked: dump_radiators != null,
      steps: evals,
      warnings: extra_warns.concat(evals.flatMap((e) => e.warnings)),
      bottleneck: bot,
      curve,
      notes: ["Optimizer found no operable placement at the target temperature."],
    });
  }

  const evals = best_place.map(([r, t_hot, t_cold], i) => evaluate_step(r, t_hot, t_cold, i));

  let q_chain = Math.min(...evals.map((e) => e.q_kj_tick));
  const bot_step = evals.reduce((bestI, e, i, arr) => (e.q_kj_tick < arr[bestI].q_kj_tick ? i : bestI), 0);
  let bot = evals[bot_step].bottleneck;

  const rad_q = q_radiator_kj_tick(DUMP_RAD_DT_K, 300.0, P_ATM, 1);
  const n_rad_needed = rad_q > 0 ? Math.max(1, Math.ceil(q_chain / rad_q - 1e-9)) : 1;
  const rad_locked = dump_radiators != null;
  const n_rad = rad_locked ? dump_radiators : n_rad_needed;
  if (rad_locked) {
    const q_rad = q_radiator_kj_tick(DUMP_RAD_DT_K, 300.0, P_ATM, n_rad);
    if (q_rad + 1e-9 < q_chain) {
      extra_warns.push(
        new Warning(
          "soft",
          "dump_undersized",
          `${n_rad} dump radiators at ${DUMP_RAD_DT_K.toFixed(0)} K only dump ${q_rad.toFixed(2)} kJ/tick; chain wants ${q_chain.toFixed(2)}.`,
          0,
        ),
      );
      if (q_rad < bot.q_kj_tick) {
        bot = new Bottleneck("dump_radiators", round(q_rad, 4), "Add pipe convection radiators on the dump loop.", 0);
        q_chain = q_rad;
      }
    }
  }

  notes.push(
    `Q(T) is a broken stick: plateau ${Math.min(...evals.map((e) => e.curve.q_plateau_kj_tick)).toFixed(3)} kJ/tick ` +
      "until the load approaches T_evap, then linear in (T_cold - T_evap). Not constant down to T_cond.",
  );
  notes.push(
    `Dump radiators: ${n_rad} ` +
      (rad_locked
        ? "(locked). "
        : `(sized so dump is not the bottleneck at ${DUMP_RAD_DT_K.toFixed(0)} K over room). `) +
      `One radiator ~ ${rad_q.toFixed(3)} kJ/tick at ${DUMP_RAD_DT_K.toFixed(0)} K, >=1 atm both sides.`,
  );

  const floor = floorIfSacrifice(steps);
  if (floor === floor) {
    notes.push(
      `If you park the last evaporator at freeze+${MARGIN_K.toFixed(0)} K ` +
        `(${c_from_k(floor).toFixed(1)} C) you can go colder than the Q-max design, at lower power.`,
    );
  } else {
    notes.push("Upstream freeze/crit windows cannot couple if the last stage sits at its freeze floor.");
  }
  const curve = chainCurve(evals, t_dump);
  const all_w = extra_warns.concat(evals.flatMap((e) => e.warnings));
  return new CascadeResult({
    t_hot_C,
    t_target_C,
    t_coldest_C: round(c_from_k(evals[evals.length - 1].resolved.t_evap_K), 2),
    t_floor_if_sacrifice_C: floor === floor ? round(c_from_k(floor), 2) : Number.NaN,
    q_at_target_kj_tick: round(q_chain, 4),
    q_at_target_kj_s: round(kj_tick_to_kj_s(q_chain), 4),
    dump_radiators: n_rad,
    dump_radiators_locked: rad_locked,
    steps: evals,
    warnings: all_w,
    bottleneck: bot,
    curve,
    notes,
  });
}
