"""Pure heat-flow formulas. No I/O, no search."""

from __future__ import annotations

from cascade.constants import (
    CFHE_ETA_PER_UNIT,
    CHAMBER_HX_J_PER_TICK_K,
    P_ATM,
    R,
    RAD_J_PER_TICK_K,
    TICK_S,
)
from cascade.gases import Gas


def k_from_c(tc: float) -> float:
    return tc + 273.15


def c_from_k(t: float) -> float:
    return t - 273.15


def clamp01_atm(p_kpa: float) -> float:
    return max(0.0, min(p_kpa / P_ATM, 1.0))


def cfhe_eta(n: int) -> float:
    if n <= 0:
        return 0.0
    return 1.0 - (1.0 - CFHE_ETA_PER_UNIT) ** n


def useful_frac(gas: Gas, t_cond: float, t_evap: float, n_cfhe: int) -> float:
    """Latent fraction left after CFHE residual sensible load. None SHC → 1.0."""
    if gas.shc is None or gas.latent is None or gas.latent <= 0:
        return 1.0
    span = max(0.0, t_cond - t_evap)
    parasitic = gas.shc * span * (1.0 - cfhe_eta(n_cfhe))
    return 1.0 - parasitic / gas.latent


def q_feed_kj_tick(gas: Gas, t_cond: float, t_evap: float, n_cfhe: int, n_evap: int) -> float:
    if not gas.can_refrigerate():
        return 0.0
    uf = useful_frac(gas, t_cond, t_evap, n_cfhe)
    if uf <= 0:
        return 0.0
    return n_evap * gas.mol_per_tick_feed() * gas.latent * uf / 1000.0


def ua_chamber_kj_tick_k(p_loop: float, p_chamber: float, n_chambers: int) -> float:
    """kJ/tick/K for n chambers at given HX-loop and chamber pressures."""
    return (
        n_chambers
        * CHAMBER_HX_J_PER_TICK_K
        * clamp01_atm(p_loop)
        * clamp01_atm(p_chamber)
        / 1000.0
    )


def q_chamber_hx_kj_tick(
    dt: float, p_loop: float, p_chamber: float, n_chambers: int = 1
) -> float:
    if dt <= 0:
        return 0.0
    return ua_chamber_kj_tick_k(p_loop, p_chamber, n_chambers) * dt


def q_radiator_kj_tick(dt: float, p_pipe: float, p_room: float, n: int = 1) -> float:
    if dt <= 0 or n <= 0:
        return 0.0
    return n * RAD_J_PER_TICK_K * dt * clamp01_atm(p_pipe) * clamp01_atm(p_room) / 1000.0


def kj_tick_to_kj_s(q: float) -> float:
    return q / TICK_S


def n_gas_ideal(p_kpa: float, t: float, volume_l: float) -> float:
    """Ideal-gas moles in a volume (L) at kPa, K."""
    if t <= 0 or volume_l <= 0 or p_kpa <= 0:
        return 0.0
    p_pa = p_kpa * 1000.0
    v_m3 = volume_l * 0.001
    return p_pa * v_m3 / (R * t)


def gas_volume_L_per_tick(n_mol_tick: float, t_K: float, p_kPa: float) -> float:
    """Ideal-gas volume (L/tick) for a molar flow at T, P."""
    if n_mol_tick <= 0 or t_K <= 0 or p_kPa <= 0:
        return 0.0
    return n_mol_tick * R * t_K / p_kPa
