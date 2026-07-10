# esp-test-utils

`esp-test-utils` provides utility helpers shared between different ESP test
frameworks. It bundles device (DUT) abstractions, serial helpers, a streaming
data monitor, xUnit reporting helpers, and a set of command line tools for
lab automation.

```{note}
The package targets Python 3.7+ and works on both POSIX and Windows. A few
features rely on Linux-only tools (for example USB hub control); those are
called out in the relevant guide.
```

## Getting started

```{toctree}
:maxdepth: 2
:caption: Getting started

installation
quickstart
```

## User guide

```{toctree}
:maxdepth: 2
:caption: User guide

guides/dut
guides/data_monitor
guides/xunit_report
guides/cli_tools
```

## API reference

```{toctree}
:maxdepth: 2
:caption: Reference

api/index
```

## Indices and tables

- {ref}`genindex`
- {ref}`modindex`
- {ref}`search`
