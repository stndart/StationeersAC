<script>
  import { cleanStep, fetchMeta, runCascade } from "./api.js";
  import Knob from "./lib/Knob.svelte";
  import Results from "./lib/Results.svelte";
  import StepCard from "./lib/StepCard.svelte";

  let nextId = 1;

  function blankStep(media = "N2") {
    return {
      id: nextId++,
      media,
      p_cond_kPa: "",
      p_evap_kPa: "",
      n_cfhe: "",
      inventory_mol: "",
      n_evap_chambers: "",
      n_cond_chambers: "",
      hx_hot_kPa: "",
      hx_cold_kPa: "",
      liquid_pipe_L: "",
    };
  }

  function presetSteps() {
    return [blankStep("X"), blankStep("CH4"), blankStep("N2")];
  }

  let tHot = $state(40);
  let tTarget = $state(-180);
  let dumpRadiators = $state("");
  let steps = $state(presetSteps());
  let meta = $state(/** @type {any} */ (null));
  let result = $state(/** @type {any} */ (null));
  let error = $state(/** @type {string | null} */ (null));
  let busy = $state(false);
  let metaError = $state(/** @type {string | null} */ (null));

  $effect(() => {
    let cancelled = false;
    fetchMeta()
      .then((m) => {
        if (!cancelled) {
          meta = m;
          metaError = null;
        }
      })
      .catch((e) => {
        if (!cancelled) metaError = e.message;
      });
    return () => {
      cancelled = true;
    };
  });

  $effect(() => {
    const payload = {
      t_hot_C: Number(tHot),
      t_target_C: Number(tTarget),
      dump_radiators: dumpRadiators === "" ? null : Number(dumpRadiators),
      steps: steps.map(cleanStep),
    };
    const ac = new AbortController();
    const timer = setTimeout(async () => {
      busy = true;
      try {
        const data = await runCascade(payload, ac.signal);
        result = data;
        error = null;
      } catch (e) {
        if (e && e.name === "AbortError") return;
        error = e instanceof Error ? e.message : String(e);
      } finally {
        busy = false;
      }
    }, 200);
    return () => {
      clearTimeout(timer);
      ac.abort();
    };
  });

  function addStep() {
    const last = steps[steps.length - 1];
    steps = [...steps, blankStep(last?.media || "N2")];
  }

  function resetPreset() {
    tHot = 40;
    tTarget = -180;
    dumpRadiators = "";
    steps = presetSteps();
  }

  function removeStep(i) {
    if (steps.length < 2) return;
    steps = steps.filter((_, j) => j !== i);
  }

  function move(i, dir) {
    const j = i + dir;
    if (j < 0 || j >= steps.length) return;
    const copy = [...steps];
    const tmp = copy[i];
    copy[i] = copy[j];
    copy[j] = tmp;
    steps = copy;
  }

  const status = $derived(
    metaError ? "backend down" : error ? "error" : busy ? "computing" : result ? "live" : "idle"
  );
</script>

<div class="app">
  <header class="topbar">
    <h1>Stationeers cascade constructor</h1>
    <span class="sub">Python solver · evaporator / condenser / CFHE</span>
    <span class="status" class:live={status === "live"} class:bad={!!metaError || !!error}>{status}</span>
  </header>
  <div class="shell">
    <aside class="constructor">
      <h2>Boundaries</h2>
      <div class="globals">
        <Knob label="Dump / room T" unit="C" bind:value={tHot} required />
        <Knob label="Target cold T" unit="C" bind:value={tTarget} required />
        <Knob label="Dump radiators" unit="count" bind:value={dumpRadiators} step="1" min="1" />
      </div>
      <div class="row-actions">
        <button class="btn" type="button" onclick={addStep}>Add step</button>
        <button class="btn ghost" type="button" onclick={resetPreset}>X / CH4 / N2 preset</button>
      </div>
      <h2>Steps (0 = dump / hottest)</h2>
      {#each steps as s, i (s.id)}
        <StepCard
          bind:step={steps[i]}
          index={i}
          gases={meta?.gases ?? []}
          canRemove={steps.length > 1}
          onRemove={() => removeStep(i)}
          onUp={() => move(i, -1)}
          onDown={() => move(i, 1)}
        />
      {/each}
    </aside>
    <main class="results">
      {#if metaError}
        <div class="error-box">
          Cannot reach the Python backend. From <code>stationeers-AC</code> run
          <code>python -m cascade.server</code>, then keep this Vite app on port 5173.
          <div class="tiny">{metaError}</div>
        </div>
      {:else if error && !result}
        <div class="error-box">{error}</div>
      {:else if result}
        {#if error}
          <div class="error-box">{error}</div>
        {/if}
        <Results {result} />
      {:else}
        <p class="tiny">Waiting for first solve…</p>
      {/if}
    </main>
  </div>
</div>
