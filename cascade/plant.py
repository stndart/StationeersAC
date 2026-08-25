"""End-setup plant schematic: devices and valve setpoints from a CascadeResult.

Flow-matching valves are derived outputs (mol/tick match), not optimizer knobs.
Coupling / dump media are schematic recommendations only.
"""

from __future__ import annotations

from typing import Any

from cascade.constants import (
    DEFAULT_HX_LOOP_KPA,
    DUMP_RAD_DT_K,
    EVAP_TARGET_L,
    LIQUID_FEED_L_PER_TICK,
    P_MAX_LIQUID_KPA,
)
from cascade.gases import GASES, Gas, get_gas
from cascade.models import CascadeResult, StepEval
from cascade.physics import c_from_k, cfhe_eta, gas_volume_L_per_tick

DUMP_CANDIDATES = ("X", "N2O")
COUPLING_CANDIDATES = ("H2", "X", "N2O", "N2", "CH4", "O2")


def _r(x: float, nd: int = 3) -> float:
    return round(float(x), nd)


def _valve(
    vid: str,
    step: int | None,
    role: str,
    device: str,
    setting: float | str | None,
    unit: str,
    note: str,
) -> dict[str, Any]:
    return {
        "id": vid,
        "step": step,
        "role": role,
        "device": device,
        "setting": setting,
        "unit": unit,
        "note": note,
    }


def stays_vapor(gas: Gas, t_K: float, p_kPa: float, margin: float = 1.2) -> bool:
    """True if the species will not condense at (T, P)."""
    if t_K <= 0 or p_kPa <= 0:
        return False
    if gas.t_crit is not None and t_K >= gas.t_crit:
        return True
    if gas.t_freeze is not None and t_K < gas.t_freeze:
        return False
    try:
        ps = gas.p_sat(t_K)
    except (ValueError, OverflowError):
        return False
    return p_kPa * margin < ps


def suggest_gas(t_K: float, p_kPa: float, candidates: tuple[str, ...]) -> dict[str, Any]:
    picked: list[dict[str, Any]] = []
    for sym in candidates:
        gas = GASES.get(sym) or get_gas(sym)
        ok = stays_vapor(gas, t_K, p_kPa)
        picked.append({"symbol": gas.symbol, "name": gas.name, "ok": ok})
        if ok:
            return {
                "symbol": gas.symbol,
                "name": gas.name,
                "ok": True,
                "reason": f"{gas.symbol} stays vapor at {c_from_k(t_K):.0f} C / {p_kPa:.0f} kPa",
                "candidates": picked,
            }
    return {
        "symbol": None,
        "name": None,
        "ok": False,
        "reason": f"No catalog gas in {list(candidates)} stays vapor at {c_from_k(t_K):.0f} C / {p_kPa:.0f} kPa",
        "candidates": picked,
    }


def _step_valves(i: int, ev: StepEval, next_hx_hot: float | None) -> list[dict[str, Any]]:
    rs = ev.resolved
    gas = get_gas(rs.media)
    n_evap = rs.n_evap_chambers
    feed_L = LIQUID_FEED_L_PER_TICK * n_evap
    mol_tick = 0.0
    if gas.v_liq:
        mol_tick = n_evap * gas.mol_per_tick_feed()
    gas_L = gas_volume_L_per_tick(mol_tick, rs.t_evap_K, rs.p_evap_kPa)
    coupling_p = rs.hx_cold_kPa
    note_mismatch = ""
    if next_hx_hot is not None and abs(next_hx_hot - coupling_p) > 1.0:
        note_mismatch = f" Next condenser HX loop is {next_hx_hot:.0f} kPa; match them on one pipe."

    valves = [
        _valve(
            f"s{i}-cond-p",
            i,
            "cond_pressure",
            "Condensation Chamber",
            _r(rs.p_cond_kPa, 1),
            "kPa",
            f"In-game pressure setting. T_sat ≈ {c_from_k(rs.t_cond_K):.1f} C. x{rs.n_cond_chambers} chamber(s).",
        ),
        _valve(
            f"s{i}-evap-liq",
            i,
            "evap_liquid_reg",
            "Evaporation Chamber liquid volume regulator",
            EVAP_TARGET_L,
            "L",
            f"Hold {EVAP_TARGET_L:.0f} L. Internal feed {feed_L:.2f} L/tick ({n_evap} x {LIQUID_FEED_L_PER_TICK} L/tick).",
        ),
        _valve(
            f"s{i}-evap-bp",
            i,
            "evap_backpressure",
            "Pressure Regulator (evaporator gas outlet)",
            _r(rs.p_evap_kPa, 1),
            "kPa",
            f"Holds T_evap ≈ {c_from_k(rs.t_evap_K):.1f} C. x{n_evap} chamber(s).",
        ),
        _valve(
            f"s{i}-liq-pump",
            i,
            "liquid_pump",
            "Volume Pump (liquid CFHE side)",
            _r(feed_L, 3),
            "L/tick",
            f"Match chamber liquid feed. {mol_tick:.3f} mol/tick of {rs.media}.",
        ),
        _valve(
            f"s{i}-gas-pump",
            i,
            "gas_pump",
            "Volume Pump (gas CFHE side)",
            _r(gas_L, 3),
            "L/tick",
            f"Same {mol_tick:.3f} mol/tick at evap {c_from_k(rs.t_evap_K):.1f} C / {rs.p_evap_kPa:.0f} kPa so CFHE mol-flows match.",
        ),
        _valve(
            f"s{i}-purge",
            i,
            "purge",
            "Pressure Relief Valve (liquid line flash purge)",
            P_MAX_LIQUID_KPA,
            "kPa",
            "Dump flash gas or the liquid pipe hits 6 MPa. Vent to a waste tank.",
        ),
        _valve(
            f"s{i}-owv-liq",
            i,
            "owv_liquid",
            "One-Way Valve (liquid)",
            "toward evaporator",
            "",
            "Prevents reverse flow through the CFHE liquid path.",
        ),
        _valve(
            f"s{i}-owv-gas",
            i,
            "owv_gas",
            "One-Way Valve (gas)",
            "toward condenser",
            "",
            "Prevents reverse flow through the CFHE gas path.",
        ),
        _valve(
            f"s{i}-coupling",
            i,
            "coupling_pr",
            "Pressure Regulator (cold HX / coupling loop)",
            _r(coupling_p, 1),
            "kPa",
            ("Keep ≥1 atm or chamber HX derates." + note_mismatch),
        ),
    ]
    return valves


def _stage_dict(i: int, ev: StepEval, next_hx_hot: float | None) -> dict[str, Any]:
    rs = ev.resolved
    gas = get_gas(rs.media)
    mol_tick = 0.0
    n_evap = rs.n_evap_chambers
    n_evap_feed = LIQUID_FEED_L_PER_TICK * n_evap
    if gas.v_liq:
        mol_tick = n_evap * gas.mol_per_tick_feed()
    coupling_p = rs.hx_cold_kPa
    coupling_t = ev.t_cold_K
    return {
        "index": i,
        "media": rs.media,
        "name": gas.name,
        "operable": ev.operable,
        "q_kj_tick": ev.q_kj_tick,
        "bottleneck": ev.bottleneck.to_dict(),
        "condenser": {
            "t_C": _r(c_from_k(rs.t_cond_K), 2),
            "p_kPa": _r(rs.p_cond_kPa, 1),
            "n_chambers": rs.n_cond_chambers,
            "hx_loop_kPa": _r(rs.hx_hot_kPa, 1),
        },
        "evaporator": {
            "t_C": _r(c_from_k(rs.t_evap_K), 2),
            "p_kPa": _r(rs.p_evap_kPa, 1),
            "n_chambers": n_evap,
            "hx_loop_kPa": _r(rs.hx_cold_kPa, 1),
            "liquid_reg_L": EVAP_TARGET_L,
            "feed_L_tick": _r(n_evap_feed, 3),
        },
        "cfhe": {
            "n": rs.n_cfhe,
            "eta": _r(cfhe_eta(rs.n_cfhe), 4),
            "mol_tick": _r(mol_tick, 4),
            "liquid_L_tick": _r(n_evap_feed, 3),
            "gas_L_tick": _r(gas_volume_L_per_tick(mol_tick, rs.t_evap_K, rs.p_evap_kPa), 3),
        },
        "inventory": {
            "mol_min": ev.inventory.mol_min,
            "mol_max": ev.inventory.mol_max,
            "chosen_mol": ev.inventory.chosen_mol,
            "in_band": ev.inventory.in_band,
            "note": ev.inventory.note,
            "liquid_pipe_L": rs.liquid_pipe_L,
        },
        "ports": {
            "t_hot_C": _r(c_from_k(ev.t_hot_K), 2),
            "t_cold_C": _r(c_from_k(ev.t_cold_K), 2),
        },
        "coupling_out": {
            "t_C": _r(c_from_k(coupling_t), 2),
            "p_kPa": _r(coupling_p, 1),
            "media": suggest_gas(coupling_t, coupling_p, COUPLING_CANDIDATES),
        },
        "valves": _step_valves(i, ev, next_hx_hot),
    }


def _format_ascii(plant: dict[str, Any]) -> str:
    lines: list[str] = []
    a = lines.append
    dump = plant["dump"]
    a("Stationeers cascade  --  end setup (devices + valves)")
    a("=" * 56)
    a(f"Dump {dump['t_room_C']:.1f} C room  ->  load {plant['load']['t_C']:.1f} C")
    a("")
    dump_gas = dump["media"]["symbol"] or "?"
    a(f"  [{dump['t_room_C']:.0f} C ROOM]")
    a(f"       |  dump PR {dump['p_kPa']:.0f} kPa   gas {dump_gas}")
    a(f"       |  convection radiators x{dump['radiators']}  (pipe ~{dump['t_pipe_C']:.0f} C, dT {dump['dt_K']:.0f} K)")
    a("       v")
    for st in plant["stages"]:
        i = st["index"]
        c = st["condenser"]
        e = st["evaporator"]
        cf = st["cfhe"]
        a(f"  [ S{i} CONDENSER  {st['media']:<4}  {c['t_C']:.1f} C  {c['p_kPa']:.0f} kPa  x{c['n_chambers']} ]")
        a(f"       |  Condensation Chamber pressure = {c['p_kPa']:.0f} kPa")
        a(f"       |  vapor -> CFHE x{cf['n']} (eta {cf['eta']:.2f})")
        a(f"       |  gas VP {cf['gas_L_tick']:.3f} L/tick   liquid VP {cf['liquid_L_tick']:.3f} L/tick")
        a(f"       |  OWV gas->cond / OWV liquid->evap   purge <= {P_MAX_LIQUID_KPA:.0f} kPa")
        a("       v")
        a(f"  [ S{i} EVAPORATOR {st['media']:<4}  {e['t_C']:.1f} C  {e['p_kPa']:.0f} kPa  x{e['n_chambers']} ]")
        a(f"       |  liquid vol reg {e['liquid_reg_L']:.0f} L, feed {e['feed_L_tick']:.2f} L/tick")
        a(f"       |  evap gas PR {e['p_kPa']:.0f} kPa")
        coup = st["coupling_out"]
        sug = coup["media"]["symbol"] or "?"
        a(f"       |  coupling PR {coup['p_kPa']:.0f} kPa  @ {coup['t_C']:.1f} C   gas {sug}")
        a("       v")
    a(f"  [ LOAD  {plant['load']['t_C']:.1f} C ]")
    a("")
    a("Valve list:")
    for v in plant["valves"]:
        step = f"S{v['step']} " if v["step"] is not None else ""
        setting = v["setting"]
        unit = f" {v['unit']}" if v["unit"] else ""
        a(f"  - {step}{v['device']}: {setting}{unit}")
        a(f"      {v['note']}")
    return "\n".join(lines) + "\n"


def plant_from_result(r: CascadeResult) -> dict[str, Any]:
    dump_p = DEFAULT_HX_LOOP_KPA
    if r.steps:
        dump_p = r.steps[0].resolved.hx_hot_kPa
    t_pipe_K = r.t_hot_C + 273.15 + DUMP_RAD_DT_K
    dump_media = suggest_gas(t_pipe_K, dump_p, DUMP_CANDIDATES)
    stages: list[dict[str, Any]] = []
    n = len(r.steps)
    for i, ev in enumerate(r.steps):
        next_hx = r.steps[i + 1].resolved.hx_hot_kPa if i + 1 < n else None
        stages.append(_stage_dict(i, ev, next_hx))

    dump_valves = [
        _valve(
            "dump-pr",
            None,
            "dump_pr",
            "Pressure Regulator (dump loop)",
            _r(dump_p, 1),
            "kPa",
            f"Pipe convection radiators on one gas pipe. Suggested media: {dump_media['symbol'] or '?'}.",
        ),
        _valve(
            "dump-rad",
            None,
            "dump_radiators",
            "Pipe Convection Radiator",
            r.dump_radiators,
            "count",
            f"Sized at {DUMP_RAD_DT_K:.0f} K over room, pipe >=1 atm both sides."
            + (" Locked." if r.dump_radiators_locked else " Auto-sized so dump is not the bottleneck."),
        ),
    ]
    all_valves = dump_valves + [v for st in stages for v in st["valves"]]
    plant = {
        "dump": {
            "t_room_C": r.t_hot_C,
            "t_pipe_C": _r(c_from_k(t_pipe_K), 2),
            "dt_K": DUMP_RAD_DT_K,
            "p_kPa": _r(dump_p, 1),
            "radiators": r.dump_radiators,
            "radiators_locked": r.dump_radiators_locked,
            "media": dump_media,
        },
        "stages": stages,
        "load": {"t_C": r.t_target_C},
        "valves": all_valves,
        "ascii": "",
    }
    plant["ascii"] = _format_ascii(plant)
    return plant
