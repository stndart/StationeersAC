<script>
  /** @type {{ curve?: { samples?: { t_C: number, q_kj_tick: number }[], t_evap_C?: number, t_break_C?: number, q_plateau_kj_tick?: number }, target_C?: number }} */
  let { curve, target_C } = $props();

  const pad = { l: 44, r: 12, t: 12, b: 28 };
  const W = 640;
  const H = 220;

  const pts = $derived(curve?.samples ?? []);

  const xr = $derived.by(() => {
    if (!pts.length) return { lo: -200, hi: 40 };
    const xs = pts.map((p) => p.t_C);
    if (target_C != null) xs.push(target_C);
    return { lo: Math.min(...xs), hi: Math.max(...xs) };
  });

  const yr = $derived.by(() => {
    if (!pts.length) return { lo: 0, hi: 1 };
    const ys = pts.map((p) => p.q_kj_tick);
    return { lo: 0, hi: Math.max(...ys, 0.01) };
  });

  function x(t) {
    const span = xr.hi - xr.lo || 1;
    return pad.l + ((t - xr.lo) / span) * (W - pad.l - pad.r);
  }

  function y(q) {
    const span = yr.hi - yr.lo || 1;
    return pad.t + (1 - (q - yr.lo) / span) * (H - pad.t - pad.b);
  }

  const d = $derived(
    pts.map((p, i) => `${i ? "L" : "M"} ${x(p.t_C).toFixed(1)} ${y(p.q_kj_tick).toFixed(1)}`).join(" ")
  );

  const ticksX = $derived([xr.lo, (xr.lo + xr.hi) / 2, xr.hi]);
  const ticksY = $derived([0, yr.hi / 2, yr.hi]);
</script>

<div class="chart">
  <svg viewBox="0 0 {W} {H}" role="img" aria-label="Cooling power versus cold temperature">
    {#each ticksY as q}
      <line x1={pad.l} x2={W - pad.r} y1={y(q)} y2={y(q)} stroke="#2c3340" />
      <text x={pad.l - 6} y={y(q) + 3} text-anchor="end" fill="#8b929e" font-size="10"
        >{q.toFixed(2)}</text
      >
    {/each}
    {#each ticksX as t}
      <text x={x(t)} y={H - 8} text-anchor="middle" fill="#8b929e" font-size="10">{t.toFixed(0)}</text>
    {/each}
    <text x={W / 2} y={H - 1} text-anchor="middle" fill="#8b929e" font-size="10">T_cold (C)</text>
    <text
      x="12"
      y={H / 2}
      fill="#8b929e"
      font-size="10"
      transform="rotate(-90 12 {H / 2})">Q (kJ/tick)</text
    >
    {#if curve?.t_break_C != null}
      <line
        x1={x(curve.t_break_C)}
        x2={x(curve.t_break_C)}
        y1={pad.t}
        y2={H - pad.b}
        stroke="#c9a24a"
        stroke-dasharray="3 3"
      />
    {/if}
    {#if target_C != null}
      <line
        x1={x(target_C)}
        x2={x(target_C)}
        y1={pad.t}
        y2={H - pad.b}
        stroke="#6aa6d6"
        stroke-dasharray="2 4"
      />
    {/if}
    {#if d}
      <path d={d} fill="none" stroke="#7cbc8a" stroke-width="2" />
    {/if}
  </svg>
  <p class="tiny">
    Broken stick: plateau until T_break, then linear to 0 at T_evap
    {#if curve?.t_evap_C != null}
      ({curve.t_evap_C.toFixed(1)} C)
    {/if}. Amber = T_break, blue = target.
  </p>
</div>
