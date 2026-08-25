/** Pure heat-flow formulas. No I/O, no search. */

import {
  CFHE_ETA_PER_UNIT,
  CHAMBER_HX_J_PER_TICK_K,
  P_ATM,
  R,
  RAD_J_PER_TICK_K,
  TICK_S,
} from "./constants.js";

export function k_from_c(tc) {
  return tc + 273.15;
}

export function c_from_k(t) {
  return t - 273.15;
}

export function clamp01_atm(p_kpa) {
  return Math.max(0.0, Math.min(p_kpa / P_ATM, 1.0));
}

export function cfhe_eta(n) {
  if (n <= 0) return 0.0;
  return 1.0 - (1.0 - CFHE_ETA_PER_UNIT) ** n;
}

export function useful_frac(gas, t_cond, t_evap, n_cfhe) {
  if (gas.shc == null || gas.latent == null || gas.latent <= 0) return 1.0;
  const span = Math.max(0.0, t_cond - t_evap);
  const parasitic = gas.shc * span * (1.0 - cfhe_eta(n_cfhe));
  return 1.0 - parasitic / gas.latent;
}

export function q_feed_kj_tick(gas, t_cond, t_evap, n_cfhe, n_evap) {
  if (!gas.can_refrigerate()) return 0.0;
  const uf = useful_frac(gas, t_cond, t_evap, n_cfhe);
  if (uf <= 0) return 0.0;
  return (n_evap * gas.mol_per_tick_feed() * gas.latent * uf) / 1000.0;
}

export function ua_chamber_kj_tick_k(p_loop, p_chamber, n_chambers) {
  return (
    (n_chambers *
      CHAMBER_HX_J_PER_TICK_K *
      clamp01_atm(p_loop) *
      clamp01_atm(p_chamber)) /
    1000.0
  );
}

export function q_chamber_hx_kj_tick(dt, p_loop, p_chamber, n_chambers = 1) {
  if (dt <= 0) return 0.0;
  return ua_chamber_kj_tick_k(p_loop, p_chamber, n_chambers) * dt;
}

export function q_radiator_kj_tick(dt, p_pipe, p_room, n = 1) {
  if (dt <= 0 || n <= 0) return 0.0;
  return (n * RAD_J_PER_TICK_K * dt * clamp01_atm(p_pipe) * clamp01_atm(p_room)) / 1000.0;
}

export function kj_tick_to_kj_s(q) {
  return q / TICK_S;
}

export function n_gas_ideal(p_kpa, t, volume_l) {
  if (t <= 0 || volume_l <= 0 || p_kpa <= 0) return 0.0;
  const p_pa = p_kpa * 1000.0;
  const v_m3 = volume_l * 0.001;
  return (p_pa * v_m3) / (R * t);
}

export function gas_volume_L_per_tick(n_mol_tick, t_K, p_kPa) {
  if (n_mol_tick <= 0 || t_K <= 0 || p_kPa <= 0) return 0.0;
  return (n_mol_tick * R * t_K) / p_kPa;
}
