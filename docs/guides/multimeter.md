# Multimeter (Draft)

```{warning}
The Multimeter API is **Draft**. Signatures and behavior may change without a
deprecation period. Do not treat it as a stable public contract yet.
```

`esptest.devices.multimeter` provides a PowerMeter-like facade for bench
current / power meters. Backends are selected with `backend=`:

| Backend | Status | Guide |
|---------|--------|-------|
| `gpib` | Draft (implemented) | {doc}`guides/multimeter_gpib` |
| `joulescope` | Planned | {doc}`guides/multimeter_joulescope` |

```{toctree}
:maxdepth: 2

multimeter_gpib
multimeter_joulescope
```

The module exports `DRAFT = True`. Gate automation on that flag if you need to
wait until the API stabilizes.
