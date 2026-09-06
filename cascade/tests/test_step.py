"""Unit tests for cascade playground."""

from __future__ import annotations

import unittest

from cascade.gases import get_gas
from cascade.models import StepSpec
from cascade.optimize import optimize_step
from cascade.physics import k_from_c, c_from_k
from cascade.step import evaluate_step
from cascade.chain import run_cascade


class TestPsat(unittest.TestCase):
    def test_n2_matches_tuned_diagram(self) -> None:
        n2 = get_gas("N2")
        p = n2.p_sat(75.0)
        self.assertAlmostEqual(p, 88.79330149935275, places=8)

    def test_alias(self) -> None:
        self.assertEqual(get_gas("pollutant").symbol, "X")
        self.assertEqual(get_gas("methane").symbol, "CH4")
        self.assertEqual(get_gas("helium").symbol, "He")
        self.assertEqual(get_gas("He").symbol, "He")


class TestFreezeWarn(unittest.TestCase):
    def test_n2_below_freeze_is_hard(self) -> None:
        n2 = get_gas("N2")
        r = optimize_step(StepSpec(media="N2", p_evap_kPa=1.0, p_cond_kPa=1000.0, n_cfhe=3), 150.0, 90.0)
        # 1 kPa interpolates colder than freeze
        self.assertLess(r.t_evap_K, n2.t_freeze)  # type: ignore[operator]
        ev = evaluate_step(r, 150.0, 90.0)
        codes = {w.code for w in ev.warnings if w.severity == "hard"}
        self.assertIn("freeze", codes)
        self.assertEqual(ev.q_kj_tick, 0.0)


class TestPowerCurve(unittest.TestCase):
    def test_broken_stick(self) -> None:
        spec = StepSpec(media="X")
        t_hot = k_from_c(40)
        t_cold = k_from_c(0)
        r = optimize_step(spec, t_hot, t_cold)
        ev = evaluate_step(r, t_hot, t_cold)
        self.assertTrue(ev.operable)
        c = ev.curve
        self.assertGreater(c.q_plateau_kj_tick, 0.0)
        self.assertGreater(c.slope_kj_tick_per_K, 0.0)
        self.assertGreater(c.t_break_K, c.t_evap_K)
        self.assertAlmostEqual(c.q_at(c.t_evap_K), 0.0, places=6)
        self.assertAlmostEqual(c.q_at(c.t_break_K), c.q_plateau_kj_tick, delta=0.05)
        self.assertAlmostEqual(c.q_at(c.t_break_K + 40.0), c.q_plateau_kj_tick, delta=0.05)
        mid = 0.5 * (c.t_evap_K + c.t_break_K)
        q_mid = c.q_at(mid)
        self.assertGreater(q_mid, 0.0)
        self.assertLess(q_mid, c.q_plateau_kj_tick - 0.01)
        expected = c.slope_kj_tick_per_K * (mid - c.t_evap_K)
        self.assertAlmostEqual(q_mid, expected, delta=0.05)


class TestLock(unittest.TestCase):
    def test_locked_p_evap_not_rewritten(self) -> None:
        n2 = get_gas("N2")
        p = 400.0
        spec = StepSpec(media="N2", p_evap_kPa=p)
        r = optimize_step(spec, k_from_c(-100), k_from_c(-150))
        self.assertTrue(r.locked["p_evap_kPa"])
        self.assertAlmostEqual(r.p_evap_kPa, p, delta=0.01)
        self.assertAlmostEqual(r.t_evap_K, n2.t_sat(p), delta=0.05)

    def test_locked_t_evap_c_not_rewritten(self) -> None:
        spec = StepSpec(media="N2", t_evap_C=-150)
        r = optimize_step(spec, k_from_c(-100), k_from_c(-140))
        self.assertTrue(r.locked["t_evap_C"])
        self.assertAlmostEqual(r.t_evap_K, k_from_c(-150), delta=0.05)
        self.assertFalse(r.locked["p_evap_kPa"])


class TestHydrogenChain(unittest.TestCase):
    def test_sil_n2_h2_at_minus_245_is_h2_evap_not_n2_cond(self) -> None:
        r = run_cascade(
            steps=[StepSpec(media="Sil"), StepSpec(media="N2"), StepSpec(media="H2")],
            t_hot_C=20,
            t_target_C=-245,
        )
        self.assertGreater(r.q_at_target_kj_tick, 1.2)
        self.assertEqual(r.steps[-1].resolved.media, "H2")
        self.assertEqual(r.bottleneck.step, 2)
        self.assertEqual(r.bottleneck.kind, "evap_HX")

    def test_sil_n2_h2_at_minus_246_drop_is_h2_evap(self) -> None:
        r = run_cascade(
            steps=[StepSpec(media="Sil"), StepSpec(media="N2"), StepSpec(media="H2")],
            t_hot_C=20,
            t_target_C=-246,
        )
        self.assertGreater(r.q_at_target_kj_tick, 0.85)
        self.assertLess(r.q_at_target_kj_tick, 1.1)
        self.assertEqual(r.bottleneck.step, 2)
        self.assertEqual(r.bottleneck.kind, "evap_HX")

    def test_two_h2_stages_split_the_window(self) -> None:
        r = run_cascade(
            steps=[
                StepSpec(media="Sil"),
                StepSpec(media="N2"),
                StepSpec(media="H2"),
                StepSpec(media="H2"),
            ],
            t_hot_C=20,
            t_target_C=-245,
        )
        warm = r.steps[2]
        cold = r.steps[3]
        self.assertGreater(warm.t_hot_K - warm.t_cold_K, 5.0)
        self.assertGreater(cold.t_hot_K - cold.t_cold_K, 5.0)
        self.assertGreater(warm.t_cold_K - cold.t_cold_K, 5.0)

    def test_locked_hot_port_on_last_h2(self) -> None:
        r = run_cascade(
            steps=[
                StepSpec(media="Sil"),
                StepSpec(media="N2"),
                StepSpec(media="H2"),
                StepSpec(media="H2", t_hot_C=-230),
            ],
            t_hot_C=20,
            t_target_C=-245,
        )
        self.assertGreater(r.q_at_target_kj_tick, 0.0)
        self.assertAlmostEqual(c_from_k(r.steps[3].t_hot_K), -230.0, delta=0.05)
        self.assertAlmostEqual(c_from_k(r.steps[2].t_cold_K), -230.0, delta=0.05)


class TestChainMinQ(unittest.TestCase):
    def test_optimizer_beats_known_feasible_cooling_power(self) -> None:
        # A hand-picked, coupled chain already carries 9.4775 kJ/tick.
        # The old widest-span search ceiling stopped at only 1.2619.
        powers = []
        for hot, cold, tc, te in [(40, 20, 65, 0), (20, 0, 45, -20)]:
            spec = StepSpec(media="X", n_cfhe=1, t_cond_C=tc, t_evap_C=te)
            resolved = optimize_step(spec, k_from_c(hot), k_from_c(cold))
            ev = evaluate_step(resolved, k_from_c(hot), k_from_c(cold))
            self.assertTrue(ev.operable)
            powers.append(ev.q_kj_tick)
        self.assertAlmostEqual(min(powers), 9.4775, places=4)
        result = run_cascade([StepSpec(media="X", n_cfhe=1)] * 2, 40, 0)
        self.assertGreaterEqual(result.q_at_target_kj_tick, min(powers))
        for ev in result.steps:
            self.assertTrue(ev.operable)
            self.assertEqual(ev.resolved.n_cfhe, 1)
        self.assertAlmostEqual(result.steps[0].t_cold_K, result.steps[1].t_hot_K)
        self.assertAlmostEqual(result.q_at_target_kj_tick,
                               min(ev.q_kj_tick for ev in result.steps), places=4)

    def test_chain_q_is_min_of_steps(self) -> None:
        r = run_cascade(
            steps=[StepSpec(media="X"), StepSpec(media="CH4")],
            t_hot_C=40,
            t_target_C=-80,
        )
        self.assertTrue(r.steps)
        self.assertGreater(r.q_at_target_kj_tick, 0.0)
        step_min = min(s.q_kj_tick for s in r.steps)
        self.assertAlmostEqual(r.q_at_target_kj_tick, step_min, delta=0.05)

    def test_infeasible_media_warns(self) -> None:
        r = run_cascade(
            steps=[StepSpec(media="H2O")],
            t_hot_C=40,
            t_target_C=-180,
        )
        hard = [w for w in r.warnings if w.severity == "hard"]
        self.assertTrue(hard)
        self.assertEqual(r.q_at_target_kj_tick, 0.0)


class TestToDict(unittest.TestCase):
    def test_payload_has_resolved_and_samples(self) -> None:
        r = run_cascade(
            steps=[StepSpec(media="X"), StepSpec(media="CH4"), StepSpec(media="N2")],
            t_hot_C=40,
            t_target_C=-180,
        )
        d = r.to_dict()
        self.assertIn("samples", d["curve"])
        self.assertGreater(len(d["curve"]["samples"]), 2)
        s0 = d["steps"][0]
        for k in (
            "n_evap_chambers",
            "n_cond_chambers",
            "hx_hot_kPa",
            "hx_cold_kPa",
            "liquid_pipe_L",
            "useful_frac",
            "operable",
        ):
            self.assertIn(k, s0)
        self.assertIn("samples", s0["curve"])


class TestPlant(unittest.TestCase):
    def test_valves_and_ascii(self) -> None:
        from cascade.plant import plant_from_result

        r = run_cascade(
            steps=[StepSpec(media="X"), StepSpec(media="CH4"), StepSpec(media="N2")],
            t_hot_C=40,
            t_target_C=-180,
        )
        plant = plant_from_result(r)
        self.assertEqual(len(plant["stages"]), 3)
        roles = {v["role"] for v in plant["valves"]}
        for need in (
            "dump_pr",
            "dump_radiators",
            "cond_pressure",
            "evap_liquid_reg",
            "evap_backpressure",
            "liquid_pump",
            "gas_pump",
            "purge",
            "coupling_pr",
        ):
            self.assertIn(need, roles)
        last = plant["stages"][-1]
        self.assertEqual(last["coupling_out"]["media"]["symbol"], "He")
        self.assertIn("Condensation Chamber", plant["ascii"])
        self.assertIn("Volume Pump", plant["ascii"])
        gas_pump = next(v for v in last["valves"] if v["role"] == "gas_pump")
        self.assertGreater(float(gas_pump["setting"]), 0.0)
        liq_pump = next(v for v in last["valves"] if v["role"] == "liquid_pump")
        self.assertAlmostEqual(float(liq_pump["setting"]), 0.25, delta=1e-9)


class TestHydrogenHeliumWiki(unittest.TestCase):
    def test_h2_can_refrigerate(self) -> None:
        h2 = get_gas("H2")
        self.assertTrue(h2.can_refrigerate())
        self.assertAlmostEqual(h2.latent, 200.0)
        self.assertAlmostEqual(h2.v_liq, 0.028)
        self.assertAlmostEqual(h2.p_sat(28.11), 92.08866822389489, places=8)

    def test_helium_is_coupling_only(self) -> None:
        from cascade.plant import stays_vapor

        he = get_gas("He")
        self.assertFalse(he.can_refrigerate())
        self.assertTrue(stays_vapor(he, 40.0, 6000.0))
        self.assertTrue(stays_vapor(he, 15.0, 300.0))

    def test_sil_ch4_n2_h2_at_minus_205(self) -> None:
        r = run_cascade(
            steps=[
                StepSpec(media="Sil"),
                StepSpec(media="CH4"),
                StepSpec(media="N2"),
                StepSpec(media="H2"),
            ],
            t_hot_C=40,
            t_target_C=-205,
        )
        self.assertGreater(r.q_at_target_kj_tick, 0.0)
        self.assertEqual(r.steps[-1].resolved.media, "H2")


class TestApiHelpers(unittest.TestCase):
    def test_run_from_body(self) -> None:
        from cascade.server import run_from_body

        payload = run_from_body(
            {
                "t_hot_C": 40,
                "t_target_C": -180,
                "dump_radiators": None,
                "steps": [{"media": "X"}, {"media": "CH4", "n_cfhe": 2}, {"media": "N2"}],
            }
        )
        self.assertIn("plant", payload)
        self.assertTrue(payload["steps"][1]["locked"]["n_cfhe"])
        self.assertEqual(payload["steps"][1]["n_cfhe"], 2)


if __name__ == "__main__":
    unittest.main()
