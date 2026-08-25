<script>
  import Knob from "./Knob.svelte";

  let { step = $bindable(), index, gases = [], onRemove, onUp, onDown, canRemove } = $props();

  const refrigerants = $derived(gases.filter((g) => g.can_refrigerate));
  const others = $derived(gases.filter((g) => !g.can_refrigerate));
</script>

<article class="step-card">
  <div class="step-head">
    <span class="step-idx">S{index}</span>
    <select bind:value={step.media}>
      {#if !gases.length}
        <option value={step.media}>{step.media}</option>
      {/if}
      <optgroup label="Refrigerants">
        {#each refrigerants as g}
          <option value={g.symbol}>{g.symbol} — {g.name}</option>
        {/each}
      </optgroup>
      <optgroup label="Other / coupling">
        {#each others as g}
          <option value={g.symbol}>{g.symbol} — {g.name}</option>
        {/each}
      </optgroup>
    </select>
    <button class="btn ghost" type="button" onclick={onUp} title="Move toward dump">up</button>
    <button class="btn ghost" type="button" onclick={onDown} title="Move toward load">dn</button>
    <button class="btn ghost" type="button" onclick={onRemove} disabled={!canRemove}>x</button>
  </div>
  <div class="knobs">
    <Knob label="Condenser P" unit="kPa" bind:value={step.p_cond_kPa} />
    <Knob label="Evaporator P" unit="kPa" bind:value={step.p_evap_kPa} />
    <Knob label="CFHE count" bind:value={step.n_cfhe} step="1" min="1" />
    <Knob label="Inventory" unit="mol" bind:value={step.inventory_mol} />
    <Knob label="Evap chambers" bind:value={step.n_evap_chambers} step="1" min="1" />
    <Knob label="Cond chambers" bind:value={step.n_cond_chambers} step="1" min="1" />
    <Knob label="Hot HX loop" unit="kPa" bind:value={step.hx_hot_kPa} />
    <Knob label="Cold HX loop" unit="kPa" bind:value={step.hx_cold_kPa} />
    <Knob label="Liquid pipe" unit="L" bind:value={step.liquid_pipe_L} />
  </div>
  <p class="tiny">Empty = optimizer. Filled = locked override.</p>
</article>
