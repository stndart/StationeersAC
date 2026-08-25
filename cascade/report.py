"""Plain-text report for a CascadeResult."""

from __future__ import annotations

from cascade.models import CascadeResult
from cascade.physics import c_from_k


def format_result(r: CascadeResult) -> str:
    lines: list[str] = []
    a = lines.append
    a("Stationeers cascade playground")
    a(f"Dump {r.t_hot_C:.1f} C  ->  target {r.t_target_C:.1f} C")
    a(
        f"Q at target: {r.q_at_target_kj_tick:.3f} kJ/tick  "
        f"({r.q_at_target_kj_s:.3f} kJ/s)"
    )
    a(f"Coldest T_evap (last stage): {r.t_coldest_C:.1f} C")
    if r.t_floor_if_sacrifice_C == r.t_floor_if_sacrifice_C:
        a(f"Floor if you sacrifice power: {r.t_floor_if_sacrifice_C:.1f} C")
    else:
        a("Floor if you sacrifice power: n/a (upstream cannot couple at last-stage freeze)")
    a(f"Dump radiators: {r.dump_radiators}" + (" (locked)" if r.dump_radiators_locked else " (auto)"))
    a(
        f"Bottleneck: {r.bottleneck.kind} @ {r.bottleneck.q_kj_tick:.3f} kJ/tick"
        + (f" (step {r.bottleneck.step})" if r.bottleneck.step is not None else "")
    )
    a(f"  -> {r.bottleneck.lever}")
    a("")
    a("Q(T_cold) broken stick:")
    a(f"  T_evap {c_from_k(r.curve.t_evap_K):.1f} C  ->  Q=0")
    a(
        f"  T_break {c_from_k(r.curve.t_break_K):.1f} C  ->  plateau "
        f"{r.curve.q_plateau_kj_tick:.3f} kJ/tick ({r.curve.plateau_limited_by})"
    )
    a(f"  slope {r.curve.slope_kj_tick_per_K:.4f} kJ/tick/K below the break")
    a("  samples (T_C, kJ/tick):")
    t_hot_K = r.t_hot_C + 273.15
    for tc, q in r.curve.samples(t_hot_K):
        a(f"    {tc:8.1f}  {q:.3f}")
    a("")
    a("Steps (0 = dump / hottest):")
    for i, s in enumerate(r.steps):
        rs = s.resolved
        a(f"  [{i}] {rs.media}")
        a(
            f"      cond {c_from_k(rs.t_cond_K):.1f} C @ {rs.p_cond_kPa:.0f} kPa   "
            f"evap {c_from_k(rs.t_evap_K):.1f} C @ {rs.p_evap_kPa:.0f} kPa   CFHE x{rs.n_cfhe}"
        )
        a(
            f"      ports hot {c_from_k(s.t_hot_K):.1f} C / cold {c_from_k(s.t_cold_K):.1f} C"
        )
        a(
            f"      Q={s.q_kj_tick:.3f}  feed={s.q_feed:.3f}  evapHX={s.q_evap_hx:.3f}  "
            f"condHX={s.q_cond_hx:.3f}  uf={s.useful_frac:.3f}"
        )
        a(f"      bottleneck {s.bottleneck.kind}: {s.bottleneck.lever}")
        locked = [k for k, v in rs.locked.items() if v]
        if locked:
            a(f"      locked: {', '.join(locked)}")
        a(f"      inventory: {s.inventory.note}")
        if s.inventory.chosen_mol is not None:
            a(
                f"      chosen {s.inventory.chosen_mol:.0f} mol "
                f"({'in band' if s.inventory.in_band else 'OUT OF BAND'})"
            )
    a("")
    hard = [w for w in r.warnings if w.severity == "hard"]
    soft = [w for w in r.warnings if w.severity == "soft"]
    if hard:
        a("HARD (will not run):")
        for w in hard:
            a(f"  [{w.step}] {w.code}: {w.message}")
    if soft:
        a("SOFT:")
        for w in soft:
            a(f"  [{w.step}] {w.code}: {w.message}")
    if not hard and not soft:
        a("No warnings.")
    a("")
    for n in r.notes:
        a(n)
    return "\n".join(lines) + "\n"
