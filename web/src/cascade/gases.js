/** Gas table and tuned saturation-pressure curves. */

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
    convexity_start = null,
    convexity_end = null,
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
    this.convexity_start = convexity_start;
    this.convexity_end = convexity_end;
  }

  _exponent(t) {
    const a = this.convexity_start, b = this.convexity_end;
    if (a == null || b == null) throw new Error(`${this.symbol}: no saturation curve`);
    // Endpoint tangents preserve invalid-lock diagnostics outside the curve.
    if (t < 0) return a * t;
    if (t > 1) return 1 + (2 - b) * (t - 1);
    return (1 - t) ** 2 * t * a + (1 - t) * t ** 2 * b + t ** 2;
  }

  p_sat(t) {
    if (this.t_freeze == null || this.t_crit == null || this.p_min_cond == null || this.p_crit == null) {
      throw new Error(`${this.symbol}: no saturation curve`);
    }
    const x = (t - this.t_freeze) / (this.t_crit - this.t_freeze);
    return this.p_min_cond * (this.p_crit / this.p_min_cond) ** this._exponent(x);
  }

  t_sat(p) {
    if (this.convexity_start == null || this.convexity_end == null) {
      throw new Error(`${this.symbol}: no saturation curve`);
    }
    const exponent = Math.log(Math.max(p, 1e-9) / this.p_min_cond) / Math.log(this.p_crit / this.p_min_cond);
    let x;
    if (exponent < 0) x = exponent / this.convexity_start;
    else if (exponent > 1) x = 1 + (exponent - 1) / (2 - this.convexity_end);
    else {
      let lo = 0, hi = 1;
      for (let i = 0; i < 52; i++) {
        const mid = (lo + hi) / 2;
        if (this._exponent(mid) < exponent) lo = mid;
        else hi = mid;
      }
      x = (lo + hi) / 2;
    }
    return this.t_freeze + x * (this.t_crit - this.t_freeze);
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
    40.0,
    190.0,
    6.3,
    6000.0,
    0.0348,
    28.02,
    75.0,
    "Phase curve: zgralewski diagram (2026-04-19).",
    2.0,
    1.3655,
  ),
  O2: new Gas(
    "Oxygen",
    "O2",
    21.1,
    800,
    56.0,
    162.0,
    6.3,
    6000.0,
    0.03,
    15.99,
    90.0,
    "Phase curve: zgralewski diagram (2026-04-19).",
    1.6053,
    1.3421,
  ),
  CH4: new Gas(
    "Methane / Volatiles",
    "CH4",
    20.4,
    1000,
    81.0,
    195.0,
    6.3,
    6000.0,
    0.04,
    16.04,
    112.0,
    "Phase curve: zgralewski diagram (2026-04-19).",
    1.5126,
    1.2842,
  ),
  H2: new Gas(
    "Hydrogen",
    "H2",
    20.4,
    200,
    15.0,
    70.0,
    6.3,
    6000.0,
    0.028,
    2.0,
    28.11,
    "Phase curve: zgralewski diagram (2026-04-19).",
    2.0,
    1.3331,
  ),
  HE: new Gas(
    "Helium",
    "He",
    20.8,
    null,
    null,
    null,
    null,
    null,
    null,
    4.0,
    null,
    "Wiki Module:Gas/data. Inert; never freezes or condenses (L=0, A=B=0). Best coupling / Stirling gas (gamma 5/3, SHC 20.8, MW 4).",
  ),
  X: new Gas(
    "Pollutant",
    "X",
    24.8,
    2000,
    173.0,
    434.0,
    1800.0,
    6000.0,
    0.04,
    64.0,
    null,
    "Phase curve: zgralewski diagram (2026-04-19).",
    1.5508,
    1.3219,
  ),
  CO2: new Gas(
    "Carbon Dioxide",
    "CO2",
    28.2,
    600,
    218.0,
    266.0,
    517.0,
    6000.0,
    0.04,
    44.01,
    null,
    "Phase curve: zgralewski diagram (2026-04-19).",
    1.0709,
    1.0793,
  ),
  N2O: new Gas(
    "Nitrous Oxide",
    "N2O",
    37.2,
    4000,
    251.0,
    431.0,
    800.0,
    2000.0,
    0.026,
    46.0,
    null,
    "Phase curve: zgralewski diagram (2026-04-19).",
    1.2822,
    1.216,
  ),
  H2O: new Gas(
    "Water",
    "H2O",
    72.0,
    8000,
    273.0,
    644.0,
    6.3,
    6000.0,
    0.018,
    18.01,
    373.15,
    "Phase curve: zgralewski diagram (2026-04-19).",
    1.5942,
    1.2833,
  ),
  SIL: new Gas(
    "Silanol",
    "Sil",
    null,
    10000,
    164.0,
    822.0,
    516.0,
    6000.0,
    0.16,
    null,
    null,
    "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
    2.0,
    1.3887,
  ),
  ALC: new Gas(
    "Alcohol",
    "ALC",
    null,
    null,
    232.0,
    424.0,
    6.3,
    1000.0,
    null,
    null,
    null,
    "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
    1.3606,
    1.2204,
  ),
  HCl: new Gas(
    "Hydrochloric Acid",
    "HCl",
    null,
    null,
    247.0,
    431.0,
    6.3,
    1000.0,
    null,
    null,
    null,
    "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
    1.3058,
    1.214,
  ),
  O3: new Gas(
    "Ozone",
    "O3",
    null,
    null,
    81.0,
    304.0,
    250.0,
    6000.0,
    null,
    null,
    null,
    "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
    1.8627,
    1.369,
  ),
  N2H4: new Gas(
    "Hydrazine / Fuel",
    "N2H4",
    null,
    null,
    246.0,
    521.0,
    6.3,
    6000.0,
    null,
    null,
    null,
    "Phase curve: zgralewski diagram (2026-04-19). Missing thermal properties remain estimates or unavailable.",
    1.4565,
    1.2715,
  ),
};

const _ALIASES = {
  POLLUTANT: "X",
  METHANE: "CH4",
  VOLATILES: "CH4",
  NITROGEN: "N2",
  OXYGEN: "O2",
  HYDROGEN: "H2",
  HELIUM: "HE",
  HE: "HE",
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
