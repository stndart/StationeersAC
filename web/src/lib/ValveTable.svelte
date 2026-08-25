<script>
  /** @type {{ valves: any[] }} */
  let { valves } = $props();
</script>

<table class="valves">
  <thead>
    <tr>
      <th>Step</th>
      <th>Device</th>
      <th>Setting</th>
      <th>Note</th>
    </tr>
  </thead>
  <tbody>
    {#each valves as v}
      <tr>
        <td>{v.step == null ? "dump" : `S${v.step}`}</td>
        <td>{v.device}</td>
        <td class="set">{v.setting}{v.unit ? ` ${v.unit}` : ""}</td>
        <td>{v.note}</td>
      </tr>
    {/each}
  </tbody>
</table>
