<script>
  /** @type {{ plant: any }} */
  let { plant } = $props();

  function fmt(v, unit = "") {
    if (v == null) return "—";
    if (typeof v === "number") return `${Number.isInteger(v) ? v : v} ${unit}`.trim();
    return `${v} ${unit}`.trim();
  }

  function chipValves(valves, roles) {
    return valves.filter((v) => roles.includes(v.role));
  }
</script>

<div class="plant">
  <div class="block dump">
    <div class="title">Dump · {plant.dump.t_room_C.toFixed(1)} C room</div>
    <div class="meta">
      {plant.dump.radiators} convection radiator{plant.dump.radiators === 1 ? "" : "s"}
      · pipe {plant.dump.p_kPa} kPa · ~{plant.dump.t_pipe_C} C (dT {plant.dump.dt_K} K)
      · gas {plant.dump.media.symbol ?? "?"}
    </div>
    <div class="chips">
      {#each plant.valves.filter((v) => v.step == null) as v}
        <span class="chip">
          <b>{v.device}</b>
          <span class="set">{fmt(v.setting, v.unit)}</span>
        </span>
      {/each}
    </div>
  </div>

  {#each plant.stages as st}
    <div class="pipe"></div>
    <div class="stage">
      <div class="chamber cond">
        <div>
          <div class="title">S{st.index} condenser · {st.media}</div>
          <div class="meta">
            {st.condenser.t_C.toFixed(1)} C · {st.condenser.p_kPa} kPa · x{st.condenser.n_chambers}
            · hot port {st.ports.t_hot_C.toFixed(1)} C
          </div>
        </div>
        <div class="tiny">Q {st.q_kj_tick.toFixed(3)} kJ/tick</div>
      </div>
      <div class="chips">
        <span class="chip"><b>CFHE</b> <span class="set">x{st.cfhe.n} · η {st.cfhe.eta}</span></span>
        {#each chipValves(st.valves, ["cond_pressure", "liquid_pump", "gas_pump", "purge", "owv_liquid", "owv_gas"]) as v}
          <span class="chip">
            <b>{v.device}</b>
            <span class="set">{fmt(v.setting, v.unit)}</span>
          </span>
        {/each}
      </div>
      <div class="chamber evap">
        <div>
          <div class="title">S{st.index} evaporator · {st.media}</div>
          <div class="meta">
            {st.evaporator.t_C.toFixed(1)} C · {st.evaporator.p_kPa} kPa · x{st.evaporator.n_chambers}
            · liquid {st.evaporator.liquid_reg_L} L · feed {st.evaporator.feed_L_tick} L/tick
            · cold port {st.ports.t_cold_C.toFixed(1)} C
          </div>
        </div>
        <div class="tiny">{st.bottleneck.kind}</div>
      </div>
      <div class="chips">
        {#each chipValves(st.valves, ["evap_liquid_reg", "evap_backpressure", "coupling_pr"]) as v}
          <span class="chip">
            <b>{v.device}</b>
            <span class="set">{fmt(v.setting, v.unit)}</span>
          </span>
        {/each}
        <span class="chip">
          <b>coupling gas</b>
          <span class="set">{st.coupling_out.media.symbol ?? "?"} @ {st.coupling_out.t_C.toFixed(1)} C</span>
        </span>
      </div>
    </div>
  {/each}

  <div class="pipe"></div>
  <div class="block load">
    <div class="title">Load · {plant.load.t_C.toFixed(1)} C</div>
    <div class="meta">Cold bus / product condenser. Last coupling loop must stay vapor at this T.</div>
  </div>
</div>
