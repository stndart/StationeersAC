<script>
  let {
    label,
    unit = "",
    value = $bindable(""),
    step = "any",
    min = undefined,
    required = false,
  } = $props();
</script>

<label class="knob" class:auto={!required && (value === "" || value === null)}>
  <span class="knob-lab">{label}{#if unit}<em>{unit}</em>{/if}</span>
  <input
    type="number"
    {step}
    {min}
    placeholder={required ? "" : "auto"}
    value={value}
    oninput={(e) => {
      value = e.currentTarget.value;
    }}
  />
</label>
