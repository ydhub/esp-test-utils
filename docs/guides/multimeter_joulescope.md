# Multimeter — Joulescope (Draft / planned)

```{warning}
Joulescope backend is **not implemented yet**. This page is a placeholder so
the Multimeter guide can list GPIB and Joulescope as separate parts.
```

Planned: `backend='joulescope'` on the same `Multimeter` facade
(`list_multimeters` / `get_multimeter_specific` / `device_start` /
`measure_current` / `device_close`), with selection by `serial_number` /
`path` as in the ATS Joulescope docs.

Until then, use the GPIB backend — see {doc}`guides/multimeter_gpib`.
