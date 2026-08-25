/** Gas table and saturation-pressure interpolation. */

import { LIQUID_FEED_L_PER_TICK } from "./constants.js";

export class Gas {
  constructor(
    name,
    symbol,
    shc,
    latent,
    t_freeze,
    t_crit,
    p_min_cond,
    p_crit,
    v_liq,
    mw,
    boil_100kpa,
    notes,
    extra_points = [],
  ) {
    this.name = name;
    this.symbol = symbol;
    this.shc = shc;
    this.latent = latent;
    this.t_freeze = t_freeze;
    this.t_crit = t_crit;
    this.p_min_cond = p_min_cond;
    this.p_crit = p_crit;
    this.v_liq = v_liq;
    this.mw = mw;
    this.boil_100kpa = boil_100kpa;
    this.notes = notes;
    this.extra_points = extra_points;
  }

  anchors() {
    /** @type {[number, number][]} */
    const pts = [];
    if (this.t_freeze != null && this.p_min_cond != null) {
      pts.push([this.t_freeze, this.p_min_cond]);
    }
    pts.push(...this.extra_points);
    if (this.boil_100kpa != null) {
      pts.push([this.boil_100kpa, 100.0]);
    }
    if (this.t_crit != null && this.p_crit != null) {
      pts.push([this.t_crit, this.p_crit]);
    }
    pts.sort((a, b) => a[0] - b[0]);
    /** @type {[number, number][]} */
    const mono = [];
    for (const [t, p] of pts) {
      if (mono.some(([mt]) => Math.abs(t - mt) < 0.5)) continue;
      if (mono.length && p <= mono[mono.length - 1][1] * 0.98) continue;
      mono.push([t, p]);
    }
    if (mono.length < 2) {
      throw new Error(`${this.symbol}: need ≥2 saturation anchors`);
    }
    return mono;
  }

  _segment(t) {
    const a = this.anchors();
    let t1;
    let p1;
    let t2;
    let p2;
    if (t <= a[0][0]) {
      [t1, p1] = a[0];
      [t2, p2] = a[1];
    } else if (t >= a[a.length - 1][0]) {
      [t1, p1] = a[a.length - 2];
      [t2, p2] = a[a.length - 1];
    } else {
      [t1, p1] = a[0];
      [t2, p2] = a[1];
      for (let i = 0; i < a.length - 1; i++) {
        if (a[i][0] <= t && t <= a[i + 1][0]) {
          [t1, p1] = a[i];
          [t2, p2] = a[i + 1];
          break;
        }
      }
    }
    return [t1, p1, t2, p2];
  }

  p_sat(t) {
    const [t1, p1, t2, p2] = this._segment(t);
    const frac = t2 === t1 ? 0.0 : (t - t1) / (t2 - t1);
    const logp = Math.log10(p1) + frac * (Math.log10(p2) - Math.log10(p1));
    return 10.0 ** logp;
  }

  t_sat(p) {
    const a = this.anchors();
    const logp = Math.log10(Math.max(p, 1e-9));
    let t1;
    let p1;
    let t2;
    let p2;
    if (logp <= Math.log10(a[0][1])) {
      [t1, p1] = a[0];
      [t2, p2] = a[1];
    } else if (logp >= Math.log10(a[a.length - 1][1])) {
      [t1, p1] = a[a.length - 2];
      [t2, p2] = a[a.length - 1];
    } else {
      [t1, p1] = a[0];
      [t2, p2] = a[1];
      for (let i = 0; i < a.length - 1; i++) {
        if (a[i][1] <= p && p <= a[i + 1][1]) {
          [t1, p1] = a[i];
          [t2, p2] = a[i + 1];
          break;
        }
      }
    }
    const frac = (logp - Math.log10(p1)) / (Math.log10(p2) - Math.log10(p1));
    return t1 + frac * (t2 - t1);
  }

  mol_per_tick_feed() {
    if (!this.v_liq) {
      throw new Error(`${this.symbol}: missing liquid molar volume`);
    }
    return LIQUID_FEED_L_PER_TICK / this.v_liq;
  }

  can_refrigerate() {
    return (
      this.latent != null &&
      this.v_liq != null &&
      this.t_freeze != null &&
      this.t_crit != null &&
      this.p_min_cond != null &&
      this.p_crit != null
    );
  }
}

/** @type {Record<string, Gas>} */
export const GASES = {
  N2: new Gas(
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
    [[75.0, 100.0]],
  ),
  O2: new Gas(
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
    [[81.0, 250.0]],
  ),
  CH4: new Gas(
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
    [[91.0, 6.0]],
  ),
  H2: new Gas(
    "Hydrogen",
    "H2",
    20.4,
    null,
    15.0,
    70.0,
    6.0,
    6000,
    null,
    2.0,
    null,
    "Chart 2026-04-19. Coupling gas / LH2; not a -180 C refrigerant.",
  ),
  X: new Gas(
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
    null,
    "Min condensation 1.8 MPa at freeze. Typical stage-1 media.",
    [[173.0, 1800.0]],
  ),
  CO2: new Gas(
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
    null,
    "T_crit -8 C: cannot dump at +40 C.",
  ),
  N2O: new Gas(
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
    null,
    "Dumps at +40 C but freeze -21 C.",
  ),
  H2O: new Gas(
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
  SIL: new Gas(
    "Silanol",
    "Sil",
    null,
    10000,
    164.0,
    821.669,
    516,
    6000,
    0.16,
    null,
    null,
    "Late-game stage-1. Missing SHC — CFHE parasitic assumed 0.",
  ),
  ALC: new Gas(
    "Alcohol",
    "ALC",
    null,
    null,
    232.0,
    424.0,
    6.0,
    1000,
    null,
    null,
    null,
    "Chart only. Missing L / V_liq / SHC.",
  ),
  HCl: new Gas(
    "Hydrochloric Acid",
    "HCl",
    null,
    null,
    247.0,
    431.0,
    6.0,
    2000,
    null,
    null,
    null,
    "Chart only. Missing L / V_liq / SHC.",
  ),
  O3: new Gas(
    "Ozone",
    "O3",
    null,
    null,
    null,
    304.0,
    null,
    6000,
    null,
    null,
    null,
    "T_crit 31 C. Cannot dump at +40 C.",
  ),
  N2H4: new Gas(
    "Hydrazine / Fuel",
    "N2H4",
    null,
    null,
    null,
    521.0,
    null,
    6000,
    null,
    null,
    null,
    "Hypergolic / toxic — do not use as AC media.",
  ),
};

const _ALIASES = {
  POLLUTANT: "X",
  METHANE: "CH4",
  VOLATILES: "CH4",
  NITROGEN: "N2",
  OXYGEN: "O2",
  HYDROGEN: "H2",
  WATER: "H2O",
  STEAM: "H2O",
  SILANOL: "SIL",
  SIL: "SIL",
  ALCOHOL: "ALC",
  NITROUS: "N2O",
  "NITROUS OXIDE": "N2O",
  "CARBON DIOXIDE": "CO2",
  HYDRAZINE: "N2H4",
  FUEL: "N2H4",
  OZONE: "O3",
  ACID: "HCL",
  HCL: "HCL",
};

export function get_gas(key) {
  const raw = String(key).trim();
  const upper = raw.toUpperCase().replace(/ /g, "");
  if (Object.prototype.hasOwnProperty.call(GASES, upper)) {
    return GASES[upper];
  }
  const alias = _ALIASES[raw.toUpperCase()] || _ALIASES[upper];
  if (alias === "HCL") return GASES.HCl;
  if (alias && Object.prototype.hasOwnProperty.call(GASES, alias)) {
    return GASES[alias];
  }
  for (const g of Object.values(GASES)) {
    if (g.symbol.toUpperCase() === upper || g.name.toUpperCase() === raw.toUpperCase()) {
      return g;
    }
  }
  throw new Error(`unknown media ${JSON.stringify(key)}; known: ${Object.keys(GASES).sort()}`);
}
