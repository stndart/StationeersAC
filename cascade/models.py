"""JSON-friendly result types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Severity = Literal["hard", "soft"]
BottleneckKind = Literal["liquid_feed", "evap_HX", "cond_HX", "cfhe", "coupling", "dump_radiators", "none"]


@dataclass
class StepSpec:
    """User-facing knobs. None = optimizer. Set = locked."""

    media: str
    p_cond_kPa: float | None = None
    p_evap_kPa: float | None = None
    t_cond_C: float | None = None
    t_evap_C: float | None = None
    t_hot_C: float | None = None
    t_cold_C: float | None = None
    n_cfhe: int | None = None
    inventory_mol: float | None = None
    n_evap_chambers: int | None = None
    n_cond_chambers: int | None = None
    hx_hot_kPa: float | None = None
    hx_cold_kPa: float | None = None
    liquid_pipe_L: float | None = None


@dataclass
class Warning:
    severity: Severity
    code: str
    message: str
    step: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Bottleneck:
    kind: BottleneckKind
    q_kj_tick: float
    lever: str
    step: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InventoryBand:
    mol_min: float
    mol_max: float
    note: str
    chosen_mol: float | None = None
    in_band: bool | None = None


@dataclass
class PowerCurve:
    """Broken-stick Q(T_cold) at fixed T_evap / T_cond / T_hot.

    Plateau while T_cold >= t_break_K, then linear down to 0 at t_evap_K.
    """

    t_evap_K: float
    t_break_K: float
    q_plateau_kj_tick: float
    slope_kj_tick_per_K: float
    plateau_limited_by: str

    def q_at(self, t_cold_K: float) -> float:
        if t_cold_K <= self.t_evap_K or self.slope_kj_tick_per_K <= 0:
            return 0.0
        q_lin = self.slope_kj_tick_per_K * (t_cold_K - self.t_evap_K)
        return min(self.q_plateau_kj_tick, q_lin)

    def samples(self, t_hot_K: float, n: int = 12) -> list[tuple[float, float]]:
        """(T_C, Q_kj_tick) from T_evap to T_hot."""
        lo = self.t_evap_K
        hi = max(t_hot_K, self.t_break_K + 10.0)
        if hi <= lo:
            return [(lo - 273.15, 0.0)]
        out = []
        for i in range(n):
            t = lo + (hi - lo) * i / (n - 1)
            out.append((t - 273.15, round(self.q_at(t), 4)))
        return out

    def to_dict(self, t_hot_K: float | None = None, n: int = 24) -> dict[str, Any]:
        d = asdict(self)
        d["t_evap_C"] = self.t_evap_K - 273.15
        d["t_break_C"] = self.t_break_K - 273.15
        if t_hot_K is not None:
            d["samples"] = [
                {"t_C": t, "q_kj_tick": q} for t, q in self.samples(t_hot_K, n)
            ]
        return d


@dataclass
class StepResolved:
    media: str
    t_cond_K: float
    t_evap_K: float
    p_cond_kPa: float
    p_evap_kPa: float
    n_cfhe: int
    n_evap_chambers: int
    n_cond_chambers: int
    hx_hot_kPa: float
    hx_cold_kPa: float
    liquid_pipe_L: float
    inventory_mol: float | None
    locked: dict[str, bool] = field(default_factory=dict)


@dataclass
class StepEval:
    resolved: StepResolved
    t_hot_K: float
    t_cold_K: float
    q_feed: float
    q_evap_hx: float
    q_cond_hx: float
    q_kj_tick: float
    useful_frac: float
    warnings: list[Warning]
    bottleneck: Bottleneck
    curve: PowerCurve
    inventory: InventoryBand

    @property
    def operable(self) -> bool:
        return not any(w.severity == "hard" for w in self.warnings)


@dataclass
class CascadeResult:
    t_hot_C: float
    t_target_C: float
    t_coldest_C: float
    t_floor_if_sacrifice_C: float
    q_at_target_kj_tick: float
    q_at_target_kj_s: float
    dump_radiators: int
    dump_radiators_locked: bool
    steps: list[StepEval]
    warnings: list[Warning]
    bottleneck: Bottleneck
    curve: PowerCurve
    notes: list[str] = field(default_factory=list)

    def q_at(self, t_cold_C: float) -> float:
        return self.curve.q_at(t_cold_C + 273.15)

    def summary(self) -> str:
        from cascade.report import format_result

        return format_result(self)

    def to_dict(self) -> dict[str, Any]:
        t_hot_K = self.t_hot_C + 273.15
        return {
            "t_hot_C": self.t_hot_C,
            "t_target_C": self.t_target_C,
            "t_coldest_C": self.t_coldest_C,
            "t_floor_if_sacrifice_C": _json_float(self.t_floor_if_sacrifice_C),
            "q_at_target_kj_tick": self.q_at_target_kj_tick,
            "q_at_target_kj_s": self.q_at_target_kj_s,
            "dump_radiators": self.dump_radiators,
            "dump_radiators_locked": self.dump_radiators_locked,
            "bottleneck": self.bottleneck.to_dict(),
            "curve": self.curve.to_dict(t_hot_K),
            "warnings": [w.to_dict() for w in self.warnings],
            "notes": self.notes,
            "steps": [_step_to_dict(s, t_hot_K) for s in self.steps],
        }


def _json_float(x: float | None) -> float | None:
    if x is None:
        return None
    if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
        return None
    return x


def _step_to_dict(s: StepEval, t_hot_K: float) -> dict[str, Any]:
    rs = s.resolved
    return {
        "media": rs.media,
        "t_cond_C": rs.t_cond_K - 273.15,
        "t_evap_C": rs.t_evap_K - 273.15,
        "p_cond_kPa": rs.p_cond_kPa,
        "p_evap_kPa": rs.p_evap_kPa,
        "n_cfhe": rs.n_cfhe,
        "n_evap_chambers": rs.n_evap_chambers,
        "n_cond_chambers": rs.n_cond_chambers,
        "hx_hot_kPa": rs.hx_hot_kPa,
        "hx_cold_kPa": rs.hx_cold_kPa,
        "liquid_pipe_L": rs.liquid_pipe_L,
        "inventory_mol": rs.inventory_mol,
        "t_hot_C": s.t_hot_K - 273.15,
        "t_cold_C": s.t_cold_K - 273.15,
        "q_kj_tick": round(s.q_kj_tick, 4),
        "q_feed": round(s.q_feed, 4),
        "q_evap_hx": round(s.q_evap_hx, 4),
        "q_cond_hx": round(s.q_cond_hx, 4),
        "useful_frac": round(s.useful_frac, 4),
        "operable": s.operable,
        "bottleneck": s.bottleneck.to_dict(),
        "locked": rs.locked,
        "inventory": asdict(s.inventory),
        "curve": s.curve.to_dict(t_hot_K),
        "warnings": [w.to_dict() for w in s.warnings],
    }
