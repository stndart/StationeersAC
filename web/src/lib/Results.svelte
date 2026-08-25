<script>
  import PowerChart from "./PowerChart.svelte";
  import PlantSchema from "./PlantSchema.svelte";
  import ValveTable from "./ValveTable.svelte";

  /** @type {{ result: any }} */
  let { result } = $props();

  const hard = $derived((result.warnings || []).filter((w) => w.severity === "hard"));
  const soft = $derived((result.warnings || []).filter((w) => w.severity === "soft"));
  const floor = $derived(result.t_floor_if_sacrifice_C);
</script>

<section class="stats">
  <div class="stat">
    <div class="k">Q at target</div>
    <div class="v">
      {result.q_at_target_kj_tick.toFixed(3)}<span class="u">kJ/tick</span>
    </div>
    <div class="tiny">{result.q_at_target_kj_s.toFixed(3)} kJ/s</div>
  </div>
  <div class="stat">
    <div class="k">Bottleneck</div>
    <div class="v" style="font-size:16px">{result.bottleneck.kind}</div>
    <div class="tiny">
      {result.bottleneck.q_kj_tick.toFixed(3)} kJ/tick
      {#if result.bottleneck.step != null}· S{result.bottleneck.step}{/if}
    </div>
  </div>
  <div class="stat">
    <div class="k">Coldest T_evap</div>
    <div class="v">{result.t_coldest_C.toFixed(1)}<span class="u">C</span></div>
    <div class="tiny">
      {#if floor == null}freeze floor n/a{:else}floor if sacrifice {floor.toFixed(1)} C{/if}
    </div>
  </div>
  <div class="stat">
    <div class="k">Dump radiators</div>
    <div class="v">{result.dump_radiators}<span class="u">{result.dump_radiators_locked ? "locked" : "auto"}</span></div>
    <div class="tiny">{result.bottleneck.lever}</div>
  </div>
</section>

{#if hard.length}
  <div class="banner hard">
    <strong>Hard — will not run</strong>
    <ul class="warn-list">
      {#each hard as w}
        <li class="hard">[{w.step ?? "—"}] {w.code}: {w.message}</li>
      {/each}
    </ul>
  </div>
{/if}
{#if soft.length}
  <div class="banner soft">
    <strong>Soft</strong>
    <ul class="warn-list">
      {#each soft as w}
        <li class="soft">[{w.step ?? "—"}] {w.code}: {w.message}</li>
      {/each}
    </ul>
  </div>
{/if}

<section class="panel">
  <h2>Q vs T_cold</h2>
  <PowerChart curve={result.curve} target_C={result.t_target_C} />
</section>

{#if result.plant}
  <section class="panel">
    <h2>End setup</h2>
    <PlantSchema plant={result.plant} />
  </section>
  <section class="panel">
    <h2>Valves and settings</h2>
    <ValveTable valves={result.plant.valves} />
  </section>
  <section class="panel">
    <h2>ASCII schematic</h2>
    <pre class="ascii">{result.plant.ascii}</pre>
  </section>
{/if}

{#if result.notes?.length}
  <section class="panel notes">
    <h2>Notes</h2>
    {#each result.notes as n}
      <p>{n}</p>
    {/each}
  </section>
{/if}

{#if result.steps?.length}
  <section class="panel notes">
    <h2>Resolved steps</h2>
    {#each result.steps as s, i}
      <p>
        S{i} {s.media}: ports {s.t_hot_C.toFixed(1)} → {s.t_cold_C.toFixed(1)} C,
        cond {s.t_cond_C.toFixed(1)} C @ {s.p_cond_kPa.toFixed(0)} kPa,
        evap {s.t_evap_C.toFixed(1)} C @ {s.p_evap_kPa.toFixed(0)} kPa,
        CFHE x{s.n_cfhe}, Q {s.q_kj_tick.toFixed(3)}.
        Inventory {s.inventory.mol_min.toFixed(0)}–{s.inventory.mol_max.toFixed(0)} mol.
      </p>
    {/each}
  </section>
{/if}
