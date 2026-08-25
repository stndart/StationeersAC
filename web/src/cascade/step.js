/** Evaluate one evaporator–condenser step. No search. */

import {
  CHAMBER_VOLUME_L,
  EVAP_TARGET_L,
  LIQUID_PIPE_FILL_MAX,
  MARGIN_K,
  P_MAX_LIQUID_KPA,
  TIGHT_MARGIN_K,
} from "./constants.js";
import { get_gas } from "./gases.js";
import { Bottleneck, InventoryBand, PowerCurve, StepEval, StepResolved, Warning, round } from "./models.js";
import {
  n_gas_ideal,
  q_chamber_hx_kj_tick,
  q_feed_kj_tick,
  ua_chamber_kj_tick_k,
  useful_frac,
} from "./physics.js";

const _LEVER = {
  liquid_feed:
    "Add a parallel evaporation chamber (or a room-scale evaporator with a real liquid pump).",
  evap_HX:
    "Lower evaporator pressure (more dT) if freeze allows, raise cold-HX loop pressure to >=1 atm, or add an evaporator chamber.",
  cond_HX:
    "Raise condenser pressure (more dT) if T_crit allows, raise hot-HX loop pressure to >=1 atm, add a condenser chamber, or add dump radiators.",
  cfhe: "Add another counterflow heat exchanger (daisy-chain) to recover inlet-liquid sensible heat.",
  coupling:
    "This media cannot couple here - change refrigerant or add a stage. Pressure will not open the freeze/crit window.",
  dump_radiators: "Add pipe convection radiators on the dump loop (or raise dump-loop dT).",
  none: "No heat is moving; fix hard-fail warnings first.",
};

function inventoryBand(gas, resolved) {
  const pipe = resolved.liquid_pipe_L;
  if (!gas.v_liq) {
    return new InventoryBand(0.0, 0.0, "missing V_liq - cannot size inventory", resolved.inventory_mol, null);
  }
  const n_liq_evap = EVAP_TARGET_L / gas.v_liq;
  const n_gas = n_gas_ideal(resolved.p_evap_kPa, resolved.t_evap_K, CHAMBER_VOLUME_L);
  const n_min = n_liq_evap + n_gas;
  const n_pipe_max = (pipe * LIQUID_PIPE_FILL_MAX) / gas.v_liq;
  const n_max = n_liq_evap + n_pipe_max;
  const chosen = resolved.inventory_mol;
  const in_band = chosen == null ? null : n_min <= chosen && chosen <= n_max;
  const note =
    `Keep about ${n_min.toFixed(0)}-${n_max.toFixed(0)} mol of ${gas.symbol}: ` +
    `>=${n_min.toFixed(0)} mol holds 20 L in the evaporator plus chamber vapor; ` +
    `<=${n_max.toFixed(0)} mol stays under ${(LIQUID_PIPE_FILL_MAX * 100).toFixed(0)}% of a ${pipe.toFixed(0)} L liquid pipe. ` +
    "Inventory does not change Q once 20 L is held.";
  return new InventoryBand(round(n_min, 2), round(n_max, 2), note, chosen, in_band);
}

function hard(code, msg, step = null) {
  return new Warning("hard", code, msg, step);
}

function soft(code, msg, step = null) {
  return new Warning("soft", code, msg, step);
}

export function warnings_for(gas, resolved, t_hot_K, t_cold_K, uf, step = null) {
  const w = [];
  if (!gas.can_refrigerate()) {
    w.push(
      hard("missing_props", `${gas.symbol} is missing L / V_liq / freeze / crit - cannot refrigerate.`, step),
    );
    return w;
  }
  if (resolved.t_evap_K < gas.t_freeze) {
    w.push(
      hard(
        "freeze",
        `T_evap ${(resolved.t_evap_K - 273.15).toFixed(1)} C is below freeze ${(gas.t_freeze - 273.15).toFixed(1)} C.`,
        step,
      ),
    );
  }
  if (resolved.t_cond_K > gas.t_crit) {
    w.push(
      hard(
        "crit",
        `T_cond ${(resolved.t_cond_K - 273.15).toFixed(1)} C is above T_crit ${(gas.t_crit - 273.15).toFixed(1)} C.`,
        step,
      ),
    );
  }
  if (resolved.t_cond_K <= t_hot_K) {
    w.push(
      hard(
        "cannot_dump",
        `T_cond ${(resolved.t_cond_K - 273.15).toFixed(1)} C is not hotter than the hot sink ${(t_hot_K - 273.15).toFixed(1)} C.`,
        step,
      ),
    );
  }
  if (resolved.t_evap_K >= t_cold_K) {
    w.push(
      hard(
        "cannot_absorb",
        `T_evap ${(resolved.t_evap_K - 273.15).toFixed(1)} C is not colder than the load ${(t_cold_K - 273.15).toFixed(1)} C.`,
        step,
      ),
    );
  }
  if (uf <= 0) {
    w.push(
      hard("useful_frac", "CFHE residual sensible load exceeds latent heat - add CFHEs or shrink the T span.", step),
    );
  }
  if (resolved.p_cond_kPa > P_MAX_LIQUID_KPA + 1) {
    w.push(hard("overpressure", `P_cond ${resolved.p_cond_kPa.toFixed(0)} kPa exceeds 6 MPa liquid-pipe limit.`, step));
  }
  if (resolved.p_evap_kPa + 0.05 < gas.p_min_cond) {
    w.push(
      hard(
        "below_min_cond",
        `P_evap ${resolved.p_evap_kPa.toFixed(1)} kPa is below min condensation ${gas.p_min_cond.toFixed(1)} kPa.`,
        step,
      ),
    );
  }
  if (resolved.p_evap_kPa > P_MAX_LIQUID_KPA + 1) {
    w.push(hard("overpressure", `P_evap ${resolved.p_evap_kPa.toFixed(0)} kPa exceeds 6 MPa.`, step));
  }
  if (resolved.t_evap_K >= gas.t_freeze && resolved.t_evap_K - gas.t_freeze < TIGHT_MARGIN_K) {
    w.push(soft("tight_freeze", `Only ${(resolved.t_evap_K - gas.t_freeze).toFixed(1)} K above freeze.`, step));
  }
  if (resolved.t_cond_K <= gas.t_crit && gas.t_crit - resolved.t_cond_K < TIGHT_MARGIN_K) {
    w.push(soft("tight_crit", `Only ${(gas.t_crit - resolved.t_cond_K).toFixed(1)} K below T_crit.`, step));
  }
  if (resolved.hx_hot_kPa < 101.325) {
    w.push(soft("hx_hot_derate", `Hot HX loop ${resolved.hx_hot_kPa.toFixed(0)} kPa < 1 atm - chamber HX derates.`, step));
  }
  if (resolved.hx_cold_kPa < 101.325) {
    w.push(
      soft("hx_cold_derate", `Cold HX loop ${resolved.hx_cold_kPa.toFixed(0)} kPa < 1 atm - chamber HX derates.`, step),
    );
  }
  if (resolved.p_evap_kPa < 101.325) {
    w.push(soft("p_evap_derate", `Evaporator ${resolved.p_evap_kPa.toFixed(0)} kPa < 1 atm - chamber HX derates.`, step));
  }
  if (gas.shc == null) {
    w.push(soft("missing_shc", `${gas.symbol} has no SHC; CFHE parasitic treated as 0.`, step));
  }
  if (gas.shc && gas.latent) {
    const span_ratio = (gas.shc * Math.max(0.0, resolved.t_cond_K - resolved.t_evap_K)) / gas.latent;
    if (span_ratio > 1.5 && resolved.n_cfhe < 3) {
      w.push(
        soft("cfhe_span", `c_p*dT/L = ${span_ratio.toFixed(2)}; few CFHEs will eat most of the latent heat.`, step),
      );
    }
  }
  return w;
}

export function bottleneckOf(q_feed, q_evap, q_cond, uf, q, includeCond = true) {
  let kind;
  if (q <= 0) {
    kind = "none";
  } else {
    const parts = [
      ["liquid_feed", q_feed],
      ["evap_HX", q_evap],
    ];
    if (includeCond) parts.push(["cond_HX", q_cond]);
    kind = parts.reduce((a, b) => (b[1] < a[1] ? b : a))[0];
    if (kind === "liquid_feed" && uf < 0.85) kind = "cfhe";
  }
  return new Bottleneck(kind, round(q, 4), _LEVER[kind]);
}

export function power_curve(gas, resolved, t_hot_K) {
  const uf = useful_frac(gas, resolved.t_cond_K, resolved.t_evap_K, resolved.n_cfhe);
  const q_feed = q_feed_kj_tick(
    gas,
    resolved.t_cond_K,
    resolved.t_evap_K,
    resolved.n_cfhe,
    resolved.n_evap_chambers,
  );
  const q_cond = q_chamber_hx_kj_tick(
    resolved.t_cond_K - t_hot_K,
    resolved.hx_hot_kPa,
    resolved.p_cond_kPa,
    resolved.n_cond_chambers,
  );
  const ua_evap = ua_chamber_kj_tick_k(resolved.hx_cold_kPa, resolved.p_evap_kPa, resolved.n_evap_chambers);
  const plateau = Math.min(q_feed, q_cond);
  const limited = q_cond <= q_feed + 1e-12 ? "cond_HX" : "liquid_feed";
  const t_break = ua_evap <= 1e-12 ? resolved.t_evap_K : resolved.t_evap_K + plateau / ua_evap;
  return new PowerCurve(resolved.t_evap_K, t_break, Math.max(0.0, plateau), ua_evap, limited);
}

export function evaluate_step(resolved, t_hot_K, t_cold_K, step = null) {
  const gas = get_gas(resolved.media);
  const uf = useful_frac(gas, resolved.t_cond_K, resolved.t_evap_K, resolved.n_cfhe);
  const q_feed = q_feed_kj_tick(
    gas,
    resolved.t_cond_K,
    resolved.t_evap_K,
    resolved.n_cfhe,
    resolved.n_evap_chambers,
  );
  const q_evap = q_chamber_hx_kj_tick(
    t_cold_K - resolved.t_evap_K,
    resolved.hx_cold_kPa,
    resolved.p_evap_kPa,
    resolved.n_evap_chambers,
  );
  const q_cond = q_chamber_hx_kj_tick(
    resolved.t_cond_K - t_hot_K,
    resolved.hx_hot_kPa,
    resolved.p_cond_kPa,
    resolved.n_cond_chambers,
  );
  const warns = warnings_for(gas, resolved, t_hot_K, t_cold_K, uf, step);
  const isHard = warns.some((w) => w.severity === "hard");
  const q = isHard ? 0.0 : Math.min(q_feed, q_evap, q_cond);
  const band = inventoryBand(gas, resolved);
  if (band.in_band === false) {
    warns.push(
      soft(
        "inventory",
        `Chosen ${band.chosen_mol.toFixed(0)} mol is outside ${band.mol_min.toFixed(0)}-${band.mol_max.toFixed(0)} mol.`,
        step,
      ),
    );
  }
  let curve = power_curve(gas, resolved, t_hot_K);
  if (isHard) {
    curve = new PowerCurve(resolved.t_evap_K, resolved.t_evap_K, 0.0, 0.0, "none");
  }
  const bot = bottleneckOf(q_feed, q_evap, q_cond, uf, q);
  bot.step = step;
  return new StepEval({
    resolved,
    t_hot_K,
    t_cold_K,
    q_feed,
    q_evap_hx: q_evap,
    q_cond_hx: q_cond,
    q_kj_tick: q,
    useful_frac: uf,
    warnings: warns,
    bottleneck: bot,
    curve,
    inventory: band,
  });
}

export function resolved_from_temps(
  spec,
  gas,
  t_cond_K,
  t_evap_K,
  n_cfhe,
  n_evap,
  n_cond,
  hx_hot,
  hx_cold,
  liquid_pipe_L,
  inventory_mol,
  locked,
) {
  return new StepResolved({
    media: gas.symbol,
    t_cond_K,
    t_evap_K,
    p_cond_kPa: gas.p_sat(t_cond_K),
    p_evap_kPa: gas.p_sat(t_evap_K),
    n_cfhe,
    n_evap_chambers: n_evap,
    n_cond_chambers: n_cond,
    hx_hot_kPa: hx_hot,
    hx_cold_kPa: hx_cold,
    liquid_pipe_L,
    inventory_mol,
    locked,
  });
}

export function operable_window(gas) {
  if (gas.t_freeze == null || gas.t_crit == null) return null;
  const lo = gas.t_freeze + MARGIN_K;
  const hi = gas.t_crit - MARGIN_K;
  if (lo >= hi) return null;
  return [lo, hi];
}
