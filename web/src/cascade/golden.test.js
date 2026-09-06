import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { meta, runFromBody } from "./api.js";
import { GASES, get_gas } from "./gases.js";

const dir = dirname(fileURLToPath(import.meta.url));

function load(name) {
  return JSON.parse(readFileSync(join(dir, "fixtures", name), "utf8"));
}

function assertClose(actual, expected, eps, label) {
  assert.ok(
    Math.abs(actual - expected) <= eps,
    `${label}: ${actual} vs ${expected} (eps ${eps})`,
  );
}

test("current wiki thermal properties are complete", () => {
  // Module:Gas/data revision 28055 (2026-09-02). Keep this synchronized
  // with the equivalent Python assertion in test_gases.py.
  const expected = {
    SIL: [101.0, 10000, 0.16, 166.0],
    ALC: [33.0, 2000, 0.058, 18.0],
    HCl: [37.0, 1000, 0.028, 36.0],
    O3: [38.6, 1000, 0.026, 24.0],
    N2H4: [48.4, 4000, 0.03, 32.0],
  };
  for (const [key, properties] of Object.entries(expected)) {
    const gas = GASES[key];
    assert.deepEqual([gas.shc, gas.latent, gas.v_liq, gas.mw], properties);
    assert.equal(gas.can_refrigerate(), true, key);
  }

  assert.equal(GASES.N2.mw, 64.0);
  assert.equal(GASES.X.mw, 28.0);
  assert.equal(GASES.H2O.mw, 108.0);
  assert.equal(GASES.HE.latent, 0.0);
  assert.equal(GASES.HE.can_refrigerate(), false);
});

test("phase curves and inverse match upstream reference samples", () => {
  for (const row of load("phase_curve.json")) {
    const gas = get_gas(row.gas);
    assertClose(gas.p_sat(row.temperature_K), row.pressure_kPa, 1e-8, row.gas);
    assertClose(gas.t_sat(row.pressure_kPa), row.temperature_K, 1e-8, row.gas);
  }
  for (const gas of Object.values(GASES)) {
    if (gas.convexity_start == null) continue;
    let previous = 0;
    for (let i = -1; i <= 101; i++) {
      const t = gas.t_freeze + (gas.t_crit - gas.t_freeze) * i / 100;
      const p = gas.p_sat(t);
      assert.ok(p > previous);
      assertClose(gas.t_sat(p), t, 1e-8, gas.symbol);
      previous = p;
    }
  }
});

test("pressure locks outside the phase window remain infeasible", () => {
  for (const [media, p_evap_kPa, p_cond_kPa, code] of [
    ["N2", 1, 1000, "freeze"], ["N2O", 1000, 3000, "crit"],
  ]) {
    const got = runFromBody({t_hot_C: 20, t_target_C: 0,
      steps: [{media, p_evap_kPa, p_cond_kPa}]});
    assert.equal(got.q_at_target_kj_tick, 0);
    assert.ok(got.warnings.some(w => w.code === code && w.severity === "hard"));
  }
});

const VALVE_ROLES = [
  "dump_pr",
  "dump_radiators",
  "cond_pressure",
  "evap_liquid_reg",
  "evap_backpressure",
  "liquid_pump",
  "gas_pump",
  "purge",
  "coupling_pr",
];

test("meta gases and lockable fields match Python", () => {
  const expected = load("meta.json");
  const got = meta();
  assert.deepEqual(got.gases, expected.gases);
  assert.deepEqual(
    got.gases.map((g) => g.symbol),
    expected.gases.map((g) => g.symbol),
  );
  assert.deepEqual(
    got.lockable_fields.map((f) => f.key),
    expected.lockable_fields.map((f) => f.key),
  );
  assert.equal(got.defaults.max_cfhe, expected.defaults.max_cfhe);
});

test("default X/CH4/N2 chain matches Python Q, plant roles, last coupling", () => {
  const { input, output } = load("default_chain.json");
  const got = runFromBody(input);
  assertClose(got.q_at_target_kj_tick, output.q_at_target_kj_tick, 0.05, "q_at_target_kj_tick");
  assert.equal(got.plant.stages.length, 3);
  const roles = new Set(got.plant.valves.map((v) => v.role));
  for (const need of VALVE_ROLES) {
    assert.ok(roles.has(need), `missing valve role ${need}`);
  }
  assert.equal(got.plant.stages.at(-1).coupling_out.media.symbol, "He");
  assert.equal(
    got.plant.stages.at(-1).coupling_out.media.symbol,
    output.plant.stages.at(-1).coupling_out.media.symbol,
  );
  const gasPump = got.plant.stages.at(-1).valves.find((v) => v.role === "gas_pump");
  assert.ok(Number(gasPump.setting) > 0);
  const liqPump = got.plant.stages.at(-1).valves.find((v) => v.role === "liquid_pump");
  assertClose(Number(liqPump.setting), 0.25, 1e-9, "liquid_pump");
});

test("locked n_cfhe is not rewritten", () => {
  const { input, output } = load("locked_cfhe.json");
  const got = runFromBody(input);
  assert.equal(got.steps[1].locked.n_cfhe, true);
  assert.equal(got.steps[1].n_cfhe, 2);
  assert.equal(got.steps[1].n_cfhe, output.steps[1].n_cfhe);
  assertClose(got.q_at_target_kj_tick, output.q_at_target_kj_tick, 0.05, "q_at_target_kj_tick");
});

test("infeasible H2O warns and Q is 0", () => {
  const { input, output } = load("infeasible_h2o.json");
  const got = runFromBody(input);
  const hard = got.warnings.filter((w) => w.severity === "hard");
  assert.ok(hard.length > 0);
  assert.equal(got.q_at_target_kj_tick, 0);
  assert.equal(got.q_at_target_kj_tick, output.q_at_target_kj_tick);
});

test("Sil/N2/H2 at -246 bottlenecks on H2 evap, not N2 cond", () => {
  const got = runFromBody({
    t_hot_C: 20,
    t_target_C: -246,
    dump_radiators: null,
    steps: [{ media: "Sil" }, { media: "N2" }, { media: "H2" }],
  });
  assert.ok(got.q_at_target_kj_tick > 0.85);
  assert.ok(got.q_at_target_kj_tick < 1.1);
  assert.equal(got.bottleneck.step, 2);
  assert.equal(got.bottleneck.kind, "evap_HX");
});

test("Sil/N2/H2/H2 splits the H2 window instead of 0 K first stage", () => {
  const got = runFromBody({
    t_hot_C: 20,
    t_target_C: -245,
    dump_radiators: null,
    steps: [{ media: "Sil" }, { media: "N2" }, { media: "H2" }, { media: "H2" }],
  });
  const warm = got.steps[2];
  const cold = got.steps[3];
  assert.ok(warm.t_hot_C - warm.t_cold_C > 5, `warm ports ${warm.t_hot_C} -> ${warm.t_cold_C}`);
  assert.ok(cold.t_hot_C - cold.t_cold_C > 5, `cold ports ${cold.t_hot_C} -> ${cold.t_cold_C}`);
});

test("locked evaporator T is not rewritten", () => {
  const got = runFromBody({
    t_hot_C: -100,
    t_target_C: -140,
    dump_radiators: null,
    steps: [{ media: "N2", t_evap_C: -150 }],
  });
  assert.equal(got.steps[0].locked.t_evap_C, true);
  assertClose(got.steps[0].t_evap_C, -150, 0.05, "t_evap_C");
});


test("optimizer beats a known feasible coupled chain in kJ/tick", () => {
  const got = runFromBody({
    t_hot_C: 40,
    t_target_C: 0,
    steps: [{ media: "X", n_cfhe: 1 }, { media: "X", n_cfhe: 1 }],
  });
  // Fixed ports 40 -> 20 -> 0 C, condensers 65/45 C and evaporators
  // 0/-20 C deliver 9.4775. The old search ceiling was only 1.2619.
  assert.ok(got.q_at_target_kj_tick >= 9.4775, `Q=${got.q_at_target_kj_tick}`);
  assertClose(got.q_at_target_kj_tick, 10.2145, 0.0001, "Python regression Q");
  for (const step of got.steps) {
    assert.equal(step.operable, true);
    assert.equal(step.n_cfhe, 1);
    assert.equal(step.locked.n_cfhe, true);
  }
  assertClose(got.steps[0].t_cold_C, got.steps[1].t_hot_C, 0.0001, "coupled ports");
});
