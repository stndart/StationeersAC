/** JSON-friendly result types. */

export class StepSpec {
  constructor({
    media,
    p_cond_kPa = null,
    p_evap_kPa = null,
    n_cfhe = null,
    inventory_mol = null,
    n_evap_chambers = null,
    n_cond_chambers = null,
    hx_hot_kPa = null,
    hx_cold_kPa = null,
    liquid_pipe_L = null,
  }) {
    this.media = media;
    this.p_cond_kPa = p_cond_kPa;
    this.p_evap_kPa = p_evap_kPa;
    this.n_cfhe = n_cfhe;
    this.inventory_mol = inventory_mol;
    this.n_evap_chambers = n_evap_chambers;
    this.n_cond_chambers = n_cond_chambers;
    this.hx_hot_kPa = hx_hot_kPa;
    this.hx_cold_kPa = hx_cold_kPa;
    this.liquid_pipe_L = liquid_pipe_L;
  }
}

export class Warning {
  constructor(severity, code, message, step = null) {
    this.severity = severity;
    this.code = code;
    this.message = message;
    this.step = step;
  }

  to_dict() {
    return {
      severity: this.severity,
      code: this.code,
      message: this.message,
      step: this.step,
    };
  }
}

export class Bottleneck {
  constructor(kind, q_kj_tick, lever, step = null) {
    this.kind = kind;
    this.q_kj_tick = q_kj_tick;
    this.lever = lever;
    this.step = step;
  }

  to_dict() {
    return {
      kind: this.kind,
      q_kj_tick: this.q_kj_tick,
      lever: this.lever,
      step: this.step,
    };
  }
}

export class InventoryBand {
  constructor(mol_min, mol_max, note, chosen_mol = null, in_band = null) {
    this.mol_min = mol_min;
    this.mol_max = mol_max;
    this.note = note;
    this.chosen_mol = chosen_mol;
    this.in_band = in_band;
  }

  to_dict() {
    return {
      mol_min: this.mol_min,
      mol_max: this.mol_max,
      note: this.note,
      chosen_mol: this.chosen_mol,
      in_band: this.in_band,
    };
  }
}

export class PowerCurve {
  constructor(t_evap_K, t_break_K, q_plateau_kj_tick, slope_kj_tick_per_K, plateau_limited_by) {
    this.t_evap_K = t_evap_K;
    this.t_break_K = t_break_K;
    this.q_plateau_kj_tick = q_plateau_kj_tick;
    this.slope_kj_tick_per_K = slope_kj_tick_per_K;
    this.plateau_limited_by = plateau_limited_by;
  }

  q_at(t_cold_K) {
    if (t_cold_K <= this.t_evap_K || this.slope_kj_tick_per_K <= 0) return 0.0;
    const q_lin = this.slope_kj_tick_per_K * (t_cold_K - this.t_evap_K);
    return Math.min(this.q_plateau_kj_tick, q_lin);
  }

  samples(t_hot_K, n = 12) {
    const lo = this.t_evap_K;
    const hi = Math.max(t_hot_K, this.t_break_K + 10.0);
    if (hi <= lo) return [[lo - 273.15, 0.0]];
    const out = [];
    for (let i = 0; i < n; i++) {
      const t = lo + ((hi - lo) * i) / (n - 1);
      out.push([t - 273.15, round(this.q_at(t), 4)]);
    }
    return out;
  }

  to_dict(t_hot_K = null, n = 24) {
    const d = {
      t_evap_K: this.t_evap_K,
      t_break_K: this.t_break_K,
      q_plateau_kj_tick: this.q_plateau_kj_tick,
      slope_kj_tick_per_K: this.slope_kj_tick_per_K,
      plateau_limited_by: this.plateau_limited_by,
      t_evap_C: this.t_evap_K - 273.15,
      t_break_C: this.t_break_K - 273.15,
    };
    if (t_hot_K != null) {
      d.samples = this.samples(t_hot_K, n).map(([t, q]) => ({ t_C: t, q_kj_tick: q }));
    }
    return d;
  }
}

export class StepResolved {
  constructor({
    media,
    t_cond_K,
    t_evap_K,
    p_cond_kPa,
    p_evap_kPa,
    n_cfhe,
    n_evap_chambers,
    n_cond_chambers,
    hx_hot_kPa,
    hx_cold_kPa,
    liquid_pipe_L,
    inventory_mol,
    locked = {},
  }) {
    this.media = media;
    this.t_cond_K = t_cond_K;
    this.t_evap_K = t_evap_K;
    this.p_cond_kPa = p_cond_kPa;
    this.p_evap_kPa = p_evap_kPa;
    this.n_cfhe = n_cfhe;
    this.n_evap_chambers = n_evap_chambers;
    this.n_cond_chambers = n_cond_chambers;
    this.hx_hot_kPa = hx_hot_kPa;
    this.hx_cold_kPa = hx_cold_kPa;
    this.liquid_pipe_L = liquid_pipe_L;
    this.inventory_mol = inventory_mol;
    this.locked = locked;
  }
}

export class StepEval {
  constructor({
    resolved,
    t_hot_K,
    t_cold_K,
    q_feed,
    q_evap_hx,
    q_cond_hx,
    q_kj_tick,
    useful_frac,
    warnings,
    bottleneck,
    curve,
    inventory,
  }) {
    this.resolved = resolved;
    this.t_hot_K = t_hot_K;
    this.t_cold_K = t_cold_K;
    this.q_feed = q_feed;
    this.q_evap_hx = q_evap_hx;
    this.q_cond_hx = q_cond_hx;
    this.q_kj_tick = q_kj_tick;
    this.useful_frac = useful_frac;
    this.warnings = warnings;
    this.bottleneck = bottleneck;
    this.curve = curve;
    this.inventory = inventory;
  }

  get operable() {
    return !this.warnings.some((w) => w.severity === "hard");
  }
}

export class CascadeResult {
  constructor({
    t_hot_C,
    t_target_C,
    t_coldest_C,
    t_floor_if_sacrifice_C,
    q_at_target_kj_tick,
    q_at_target_kj_s,
    dump_radiators,
    dump_radiators_locked,
    steps,
    warnings,
    bottleneck,
    curve,
    notes = [],
  }) {
    this.t_hot_C = t_hot_C;
    this.t_target_C = t_target_C;
    this.t_coldest_C = t_coldest_C;
    this.t_floor_if_sacrifice_C = t_floor_if_sacrifice_C;
    this.q_at_target_kj_tick = q_at_target_kj_tick;
    this.q_at_target_kj_s = q_at_target_kj_s;
    this.dump_radiators = dump_radiators;
    this.dump_radiators_locked = dump_radiators_locked;
    this.steps = steps;
    this.warnings = warnings;
    this.bottleneck = bottleneck;
    this.curve = curve;
    this.notes = notes;
  }

  q_at(t_cold_C) {
    return this.curve.q_at(t_cold_C + 273.15);
  }

  to_dict() {
    const t_hot_K = this.t_hot_C + 273.15;
    return {
      t_hot_C: this.t_hot_C,
      t_target_C: this.t_target_C,
      t_coldest_C: this.t_coldest_C,
      t_floor_if_sacrifice_C: jsonFloat(this.t_floor_if_sacrifice_C),
      q_at_target_kj_tick: this.q_at_target_kj_tick,
      q_at_target_kj_s: this.q_at_target_kj_s,
      dump_radiators: this.dump_radiators,
      dump_radiators_locked: this.dump_radiators_locked,
      bottleneck: this.bottleneck.to_dict(),
      curve: this.curve.to_dict(t_hot_K),
      warnings: this.warnings.map((w) => w.to_dict()),
      notes: this.notes,
      steps: this.steps.map((s) => stepToDict(s, t_hot_K)),
    };
  }
}

export function jsonFloat(x) {
  if (x == null) return null;
  if (typeof x === "number" && (!Number.isFinite(x) || Number.isNaN(x))) return null;
  return x;
}

function stepToDict(s, t_hot_K) {
  const rs = s.resolved;
  return {
    media: rs.media,
    t_cond_C: rs.t_cond_K - 273.15,
    t_evap_C: rs.t_evap_K - 273.15,
    p_cond_kPa: rs.p_cond_kPa,
    p_evap_kPa: rs.p_evap_kPa,
    n_cfhe: rs.n_cfhe,
    n_evap_chambers: rs.n_evap_chambers,
    n_cond_chambers: rs.n_cond_chambers,
    hx_hot_kPa: rs.hx_hot_kPa,
    hx_cold_kPa: rs.hx_cold_kPa,
    liquid_pipe_L: rs.liquid_pipe_L,
    inventory_mol: rs.inventory_mol,
    t_hot_C: s.t_hot_K - 273.15,
    t_cold_C: s.t_cold_K - 273.15,
    q_kj_tick: s.q_kj_tick,
    q_feed: s.q_feed,
    q_evap_hx: s.q_evap_hx,
    q_cond_hx: s.q_cond_hx,
    useful_frac: s.useful_frac,
    operable: s.operable,
    bottleneck: s.bottleneck.to_dict(),
    locked: rs.locked,
    inventory: s.inventory.to_dict(),
    curve: s.curve.to_dict(t_hot_K),
    warnings: s.warnings.map((w) => w.to_dict()),
  };
}

export function round(x, nd = 0) {
  if (nd === 0) {
    return Math.round(x);
  }
  const f = 10 ** nd;
  return Math.round(x * f) / f;
}
