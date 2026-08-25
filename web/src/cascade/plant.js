/** End-setup plant schematic: devices and valve setpoints from a CascadeResult. */

import {
  DEFAULT_HX_LOOP_KPA,
  DUMP_RAD_DT_K,
  EVAP_TARGET_L,
  LIQUID_FEED_L_PER_TICK,
  P_MAX_LIQUID_KPA,
} from "./constants.js";
import { GASES, get_gas } from "./gases.js";
import { round } from "./models.js";
import { c_from_k, cfhe_eta, gas_volume_L_per_tick } from "./physics.js";

export const DUMP_CANDIDATES = ["X", "N2O"];
export const COUPLING_CANDIDATES = ["H2", "X", "N2O", "N2", "CH4", "O2"];

function r(x, nd = 3) {
  return round(Number(x), nd);
}

function valve(vid, step, role, device, setting, unit, note) {
  return { id: vid, step, role, device, setting, unit, note };
}

export function stays_vapor(gas, t_K, p_kPa, margin = 1.2) {
  if (t_K <= 0 || p_kPa <= 0) return false;
  if (gas.t_crit != null && t_K >= gas.t_crit) return true;
  if (gas.t_freeze != null && t_K < gas.t_freeze) return false;
  try {
    const ps = gas.p_sat(t_K);
    return p_kPa * margin < ps;
  } catch {
    return false;
  }
}

export function suggest_gas(t_K, p_kPa, candidates) {
  const picked = [];
  for (const sym of candidates) {
    const gas = GASES[sym] || get_gas(sym);
    const ok = stays_vapor(gas, t_K, p_kPa);
    picked.push({ symbol: gas.symbol, name: gas.name, ok });
    if (ok) {
      return {
        symbol: gas.symbol,
        name: gas.name,
        ok: true,
        reason: `${gas.symbol} stays vapor at ${c_from_k(t_K).toFixed(0)} C / ${p_kPa.toFixed(0)} kPa`,
        candidates: picked,
      };
    }
  }
  return {
    symbol: null,
    name: null,
    ok: false,
    reason: `No catalog gas in ${JSON.stringify([...candidates])} stays vapor at ${c_from_k(t_K).toFixed(0)} C / ${p_kPa.toFixed(0)} kPa`,
    candidates: picked,
  };
}

function stepValves(i, ev, next_hx_hot) {
  const rs = ev.resolved;
  const gas = get_gas(rs.media);
  const n_evap = rs.n_evap_chambers;
  const feed_L = LIQUID_FEED_L_PER_TICK * n_evap;
  let mol_tick = 0.0;
  if (gas.v_liq) mol_tick = n_evap * gas.mol_per_tick_feed();
  const gas_L = gas_volume_L_per_tick(mol_tick, rs.t_evap_K, rs.p_evap_kPa);
  const coupling_p = rs.hx_cold_kPa;
  let note_mismatch = "";
  if (next_hx_hot != null && Math.abs(next_hx_hot - coupling_p) > 1.0) {
    note_mismatch = ` Next condenser HX loop is ${next_hx_hot.toFixed(0)} kPa; match them on one pipe.`;
  }

  return [
    valve(
      `s${i}-cond-p`,
      i,
      "cond_pressure",
      "Condensation Chamber",
      r(rs.p_cond_kPa, 1),
      "kPa",
      `In-game pressure setting. T_sat ≈ ${c_from_k(rs.t_cond_K).toFixed(1)} C. x${rs.n_cond_chambers} chamber(s).`,
    ),
    valve(
      `s${i}-evap-liq`,
      i,
      "evap_liquid_reg",
      "Evaporation Chamber liquid volume regulator",
      EVAP_TARGET_L,
      "L",
      `Hold ${EVAP_TARGET_L.toFixed(0)} L. Internal feed ${feed_L.toFixed(2)} L/tick (${n_evap} x ${LIQUID_FEED_L_PER_TICK} L/tick).`,
    ),
    valve(
      `s${i}-evap-bp`,
      i,
      "evap_backpressure",
      "Pressure Regulator (evaporator gas outlet)",
      r(rs.p_evap_kPa, 1),
      "kPa",
      `Holds T_evap ≈ ${c_from_k(rs.t_evap_K).toFixed(1)} C. x${n_evap} chamber(s).`,
    ),
    valve(
      `s${i}-liq-pump`,
      i,
      "liquid_pump",
      "Volume Pump (liquid CFHE side)",
      r(feed_L, 3),
      "L/tick",
      `Match chamber liquid feed. ${mol_tick.toFixed(3)} mol/tick of ${rs.media}.`,
    ),
    valve(
      `s${i}-gas-pump`,
      i,
      "gas_pump",
      "Volume Pump (gas CFHE side)",
      r(gas_L, 3),
      "L/tick",
      `Same ${mol_tick.toFixed(3)} mol/tick at evap ${c_from_k(rs.t_evap_K).toFixed(1)} C / ${rs.p_evap_kPa.toFixed(0)} kPa so CFHE mol-flows match.`,
    ),
    valve(
      `s${i}-purge`,
      i,
      "purge",
      "Pressure Relief Valve (liquid line flash purge)",
      P_MAX_LIQUID_KPA,
      "kPa",
      "Dump flash gas or the liquid pipe hits 6 MPa. Vent to a waste tank.",
    ),
    valve(
      `s${i}-owv-liq`,
      i,
      "owv_liquid",
      "One-Way Valve (liquid)",
      "toward evaporator",
      "",
      "Prevents reverse flow through the CFHE liquid path.",
    ),
    valve(
      `s${i}-owv-gas`,
      i,
      "owv_gas",
      "One-Way Valve (gas)",
      "toward condenser",
      "",
      "Prevents reverse flow through the CFHE gas path.",
    ),
    valve(
      `s${i}-coupling`,
      i,
      "coupling_pr",
      "Pressure Regulator (cold HX / coupling loop)",
      r(coupling_p, 1),
      "kPa",
      "Keep ≥1 atm or chamber HX derates." + note_mismatch,
    ),
  ];
}

function stageDict(i, ev, next_hx_hot) {
  const rs = ev.resolved;
  const gas = get_gas(rs.media);
  let mol_tick = 0.0;
  const n_evap = rs.n_evap_chambers;
  const n_evap_feed = LIQUID_FEED_L_PER_TICK * n_evap;
  if (gas.v_liq) mol_tick = n_evap * gas.mol_per_tick_feed();
  const coupling_p = rs.hx_cold_kPa;
  const coupling_t = ev.t_cold_K;
  return {
    index: i,
    media: rs.media,
    name: gas.name,
    operable: ev.operable,
    q_kj_tick: ev.q_kj_tick,
    bottleneck: ev.bottleneck.to_dict(),
    condenser: {
      t_C: r(c_from_k(rs.t_cond_K), 2),
      p_kPa: r(rs.p_cond_kPa, 1),
      n_chambers: rs.n_cond_chambers,
      hx_loop_kPa: r(rs.hx_hot_kPa, 1),
    },
    evaporator: {
      t_C: r(c_from_k(rs.t_evap_K), 2),
      p_kPa: r(rs.p_evap_kPa, 1),
      n_chambers: n_evap,
      hx_loop_kPa: r(rs.hx_cold_kPa, 1),
      liquid_reg_L: EVAP_TARGET_L,
      feed_L_tick: r(n_evap_feed, 3),
    },
    cfhe: {
      n: rs.n_cfhe,
      eta: r(cfhe_eta(rs.n_cfhe), 4),
      mol_tick: r(mol_tick, 4),
      liquid_L_tick: r(n_evap_feed, 3),
      gas_L_tick: r(gas_volume_L_per_tick(mol_tick, rs.t_evap_K, rs.p_evap_kPa), 3),
    },
    inventory: {
      mol_min: ev.inventory.mol_min,
      mol_max: ev.inventory.mol_max,
      chosen_mol: ev.inventory.chosen_mol,
      in_band: ev.inventory.in_band,
      note: ev.inventory.note,
      liquid_pipe_L: rs.liquid_pipe_L,
    },
    ports: {
      t_hot_C: r(c_from_k(ev.t_hot_K), 2),
      t_cold_C: r(c_from_k(ev.t_cold_K), 2),
    },
    coupling_out: {
      t_C: r(c_from_k(coupling_t), 2),
      p_kPa: r(coupling_p, 1),
      media: suggest_gas(coupling_t, coupling_p, COUPLING_CANDIDATES),
    },
    valves: stepValves(i, ev, next_hx_hot),
  };
}

function formatAscii(plant) {
  const lines = [];
  const a = (s) => lines.push(s);
  const dump = plant.dump;
  a("Stationeers cascade  --  end setup (devices + valves)");
  a("=".repeat(56));
  a(`Dump ${dump.t_room_C.toFixed(1)} C room  ->  load ${plant.load.t_C.toFixed(1)} C`);
  a("");
  const dump_gas = dump.media.symbol || "?";
  a(`  [${dump.t_room_C.toFixed(0)} C ROOM]`);
  a(`       |  dump PR ${dump.p_kPa.toFixed(0)} kPa   gas ${dump_gas}`);
  a(
    `       |  convection radiators x${dump.radiators}  (pipe ~${dump.t_pipe_C.toFixed(0)} C, dT ${dump.dt_K.toFixed(0)} K)`,
  );
  a("       v");
  for (const st of plant.stages) {
    const i = st.index;
    const c = st.condenser;
    const e = st.evaporator;
    const cf = st.cfhe;
    a(
      `  [ S${i} CONDENSER  ${String(st.media).padEnd(4)}  ${c.t_C.toFixed(1)} C  ${c.p_kPa.toFixed(0)} kPa  x${c.n_chambers} ]`,
    );
    a(`       |  Condensation Chamber pressure = ${c.p_kPa.toFixed(0)} kPa`);
    a(`       |  vapor -> CFHE x${cf.n} (eta ${cf.eta.toFixed(2)})`);
    a(`       |  gas VP ${cf.gas_L_tick.toFixed(3)} L/tick   liquid VP ${cf.liquid_L_tick.toFixed(3)} L/tick`);
    a(`       |  OWV gas->cond / OWV liquid->evap   purge <= ${P_MAX_LIQUID_KPA.toFixed(0)} kPa`);
    a("       v");
    a(
      `  [ S${i} EVAPORATOR ${String(st.media).padEnd(4)}  ${e.t_C.toFixed(1)} C  ${e.p_kPa.toFixed(0)} kPa  x${e.n_chambers} ]`,
    );
    a(`       |  liquid vol reg ${e.liquid_reg_L.toFixed(0)} L, feed ${e.feed_L_tick.toFixed(2)} L/tick`);
    a(`       |  evap gas PR ${e.p_kPa.toFixed(0)} kPa`);
    const coup = st.coupling_out;
    const sug = coup.media.symbol || "?";
    a(`       |  coupling PR ${coup.p_kPa.toFixed(0)} kPa  @ ${coup.t_C.toFixed(1)} C   gas ${sug}`);
    a("       v");
  }
  a(`  [ LOAD  ${plant.load.t_C.toFixed(1)} C ]`);
  a("");
  a("Valve list:");
  for (const v of plant.valves) {
    const step = v.step != null ? `S${v.step} ` : "";
    const unit = v.unit ? ` ${v.unit}` : "";
    a(`  - ${step}${v.device}: ${v.setting}${unit}`);
    a(`      ${v.note}`);
  }
  return lines.join("\n") + "\n";
}

export function plant_from_result(result) {
  let dump_p = DEFAULT_HX_LOOP_KPA;
  if (result.steps.length) dump_p = result.steps[0].resolved.hx_hot_kPa;
  const t_pipe_K = result.t_hot_C + 273.15 + DUMP_RAD_DT_K;
  const dump_media = suggest_gas(t_pipe_K, dump_p, DUMP_CANDIDATES);
  const stages = [];
  const n = result.steps.length;
  for (let i = 0; i < n; i++) {
    const ev = result.steps[i];
    const next_hx = i + 1 < n ? result.steps[i + 1].resolved.hx_hot_kPa : null;
    stages.push(stageDict(i, ev, next_hx));
  }

  const dump_valves = [
    valve(
      "dump-pr",
      null,
      "dump_pr",
      "Pressure Regulator (dump loop)",
      r(dump_p, 1),
      "kPa",
      `Pipe convection radiators on one gas pipe. Suggested media: ${dump_media.symbol || "?"}.`,
    ),
    valve(
      "dump-rad",
      null,
      "dump_radiators",
      "Pipe Convection Radiator",
      result.dump_radiators,
      "count",
      `Sized at ${DUMP_RAD_DT_K.toFixed(0)} K over room, pipe >=1 atm both sides.` +
        (result.dump_radiators_locked ? " Locked." : " Auto-sized so dump is not the bottleneck."),
    ),
  ];
  const all_valves = dump_valves.concat(stages.flatMap((st) => st.valves));
  const plant = {
    dump: {
      t_room_C: result.t_hot_C,
      t_pipe_C: r(c_from_k(t_pipe_K), 2),
      dt_K: DUMP_RAD_DT_K,
      p_kPa: r(dump_p, 1),
      radiators: result.dump_radiators,
      radiators_locked: result.dump_radiators_locked,
      media: dump_media,
    },
    stages,
    load: { t_C: result.t_target_C },
    valves: all_valves,
    ascii: "",
  };
  plant.ascii = formatAscii(plant);
  return plant;
}
