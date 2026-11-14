# Orbit watch

The aim is change-point detection on public satellite orbital-element history
(TLE/GP data) to find unannounced manoeuvres, objects that keep approaching
each other, and dead objects that move. Built out of interest.

## What exists now

- `orbit_watch.elements`: parses TLEs (2-line and 3-line, checksums checked)
  and CelesTrak/Space-Track GP records in JSON and CSV into one immutable
  `ElementSet`, with a UTC epoch, the mean elements, B* and a semi-major axis
  derived the way SGP4 derives it (see the `ElementSet` docstring).
- `orbit_watch.series`: `to_series` turns element sets into an epoch-sorted,
  de-duplicated `ElementSeries` of numpy arrays per object.
- `orbit_watch.propagate`: TEME position and velocity at given UTC times through
  the `sgp4` package, raising `PropagationError` on SGP4 error codes.
- `orbit_watch.sources`: the `ElementSource` protocol and `DirectorySource`,
  which reads element files from a local directory. There is no network code yet.

## Running the tests

```
python -m venv .venv
.venv/Scripts/python -m pip install -e .[dev]   # .venv/bin/python on Linux/macOS
.venv/Scripts/python -m pytest -q
```

Test fixtures live in `mock/`; `mock/README.md` says where each one came from.
