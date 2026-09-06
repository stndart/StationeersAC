"""Reference samples from upstream calcPressure, independent of solver fixtures."""

import json
from pathlib import Path
import unittest

from cascade.gases import GASES, get_gas
from cascade.models import StepSpec
from cascade.optimize import optimize_step
from cascade.step import evaluate_step


class TestPhaseCurves(unittest.TestCase):
    def test_upstream_samples_and_inverse(self):
        path = Path(__file__).resolve().parents[2] / "web/src/cascade/fixtures/phase_curve.json"
        for row in json.loads(path.read_text()):
            with self.subTest(row=row):
                gas = get_gas(row["gas"])
                self.assertAlmostEqual(gas.p_sat(row["temperature_K"]), row["pressure_kPa"], places=8)
                self.assertAlmostEqual(gas.t_sat(row["pressure_kPa"]), row["temperature_K"], places=8)

    def test_monotonic_and_outside_roundtrip(self):
        for gas in GASES.values():
            if gas.convexity_start is None:
                continue
            previous = 0
            for i in range(-1, 102):
                t = gas.t_freeze + (gas.t_crit - gas.t_freeze) * i / 100
                p = gas.p_sat(t)
                self.assertGreater(p, previous)
                self.assertAlmostEqual(gas.t_sat(p), t, places=8)
                previous = p

    def test_pressure_above_endpoint_is_rejected(self):
        # N2O's 2 MPa curve endpoint is below the 6 MPa pipe limit.
        resolved = optimize_step(StepSpec(media="N2O", p_cond_kPa=3000, p_evap_kPa=1000), 300, 280)
        result = evaluate_step(resolved, 300, 280)
        self.assertAlmostEqual(resolved.p_cond_kPa, 3000, places=8)
        self.assertFalse(result.operable)
        self.assertIn("crit", {w.code for w in result.warnings})
