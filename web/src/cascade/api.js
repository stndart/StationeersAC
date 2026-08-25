/** Same contract as cascade.server: meta() and run_from_body(). */

import { run_cascade } from "./chain.js";
import {
  DEFAULT_HX_LOOP_KPA,
  DEFAULT_LIQUID_PIPE_L,
  DUMP_RAD_DT_K,
  EVAP_TARGET_L,
  LIQUID_FEED_L_PER_TICK,
  MAX_CFHE,
  P_MAX_LIQUID_KPA,
} from "./constants.js";
import { GASES } from "./gases.js";
import { StepSpec } from "./models.js";
import { c_from_k } from "./physics.js";
import { plant_from_result } from "./plant.js";

const INT_FIELDS = ["n_cfhe", "n_evap_chambers", "n_cond_chambers"];
const FLOAT_FIELDS = [
  "p_cond_kPa",
  "p_evap_kPa",
  "t_cond_C",
  "t_evap_C",
  "t_hot_C",
  "t_cold_C",
  "inventory_mol",
  "hx_hot_kPa",
  "hx_cold_kPa",
  "liquid_pipe_L",
];

export const LOCKABLE_FIELDS = [
  { key: "t_cond_C", label: "Condenser temperature", type: "float", unit: "C" },
  { key: "p_cond_kPa", label: "Condenser pressure", type: "float", unit: "kPa" },
  { key: "t_evap_C", label: "Evaporator temperature", type: "float", unit: "C" },
  { key: "p_evap_kPa", label: "Evaporator pressure", type: "float", unit: "kPa" },
  { key: "t_hot_C", label: "Hot port temperature", type: "float", unit: "C" },
  { key: "t_cold_C", label: "Cold port temperature", type: "float", unit: "C" },
  { key: "n_cfhe", label: "CFHE count", type: "int", unit: "" },
  { key: "inventory_mol", label: "Inventory", type: "float", unit: "mol" },
  { key: "n_evap_chambers", label: "Evaporator chambers", type: "int", unit: "" },
  { key: "n_cond_chambers", label: "Condenser chambers", type: "int", unit: "" },
  { key: "hx_hot_kPa", label: "Hot HX loop pressure", type: "float", unit: "kPa" },
  { key: "hx_cold_kPa", label: "Cold HX loop pressure", type: "float", unit: "kPa" },
  { key: "liquid_pipe_L", label: "Liquid pipe volume", type: "float", unit: "L" },
];

function gasMeta() {
  return Object.values(GASES).map((gas) => ({
    symbol: gas.symbol,
    name: gas.name,
    can_refrigerate: gas.can_refrigerate(),
    t_freeze_C: gas.t_freeze == null ? null : round2(c_from_k(gas.t_freeze)),
    t_crit_C: gas.t_crit == null ? null : round2(c_from_k(gas.t_crit)),
    notes: gas.notes,
  }));
}

function round2(x) {
  return Math.round(x * 100) / 100;
}

export function meta() {
  return {
    gases: gasMeta(),
    lockable_fields: LOCKABLE_FIELDS,
    defaults: {
      max_cfhe: MAX_CFHE,
      dump_p_kPa: DEFAULT_HX_LOOP_KPA,
      hx_loop_kPa: DEFAULT_HX_LOOP_KPA,
      evap_target_L: EVAP_TARGET_L,
      liquid_feed_L_per_tick: LIQUID_FEED_L_PER_TICK,
      liquid_pipe_L: DEFAULT_LIQUID_PIPE_L,
      dump_rad_dt_K: DUMP_RAD_DT_K,
      p_max_liquid_kPa: P_MAX_LIQUID_KPA,
      t_hot_C: 40.0,
      t_target_C: -180.0,
      preset_steps: [{ media: "X" }, { media: "CH4" }, { media: "N2" }],
    },
  };
}

function asNumber(val, kind) {
  if (val == null || val === "") return null;
  if (kind === "int") return Number.parseInt(String(val), 10);
  return Number(val);
}

/** @param {Record<string, any>} d */
export function specFromDict(d) {
  if (!d?.media) throw new Error("each step needs media");
  /** @type {Record<string, any>} */
  const kwargs = { media: String(d.media) };
  for (const k of INT_FIELDS) {
    if (k in d) kwargs[k] = asNumber(d[k], "int");
  }
  for (const k of FLOAT_FIELDS) {
    if (k in d) kwargs[k] = asNumber(d[k], "float");
  }
  return new StepSpec(kwargs);
}

/** @param {Record<string, any>} body */
export function runFromBody(body) {
  const steps_raw = body.steps || [];
  if (!steps_raw.length) throw new Error("need at least one step");
  const specs = steps_raw.map(specFromDict);
  const t_hot = Number(body.t_hot_C);
  const t_target = Number(body.t_target_C);
  const dump = body.dump_radiators;
  const dump_n = dump == null || dump === "" ? null : Number.parseInt(String(dump), 10);
  const result = run_cascade(specs, t_hot, t_target, dump_n);
  const payload = result.to_dict();
  payload.plant = plant_from_result(result);
  return payload;
}
