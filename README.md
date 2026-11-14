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

## Running on Kaggle CPU

When the laptop is busy, `tools/kaggle_run.py` runs a command on a private Kaggle CPU kernel
against the exact commit at HEAD (it refuses a working tree with uncommitted or untracked changes):

```
python tools/kaggle_run.py --slug ow-suite -- pytest -q
```

It needs the `kaggle` CLI installed and authenticated. It embeds `git archive HEAD` and the commit
SHA in a generated script kernel (written to `data/kaggle/<slug>/push/`), pushes it with
`kaggle kernels push`, checks `kaggle kernels status` every 30 seconds, and downloads the outputs
to `data/kaggle/<slug>/out/`: `COMMIT.txt`, `run.log` (stdout and stderr together),
`exit_code.txt` and anything the command wrote under `/kaggle/working/out`. It checks that
`COMMIT.txt` matches the pushed commit, prints the end of `run.log` and exits with the command's
exit code. The default command is `pytest -q`. The kernel has internet access because it runs
`pip install -e .[dev]`; each push makes a new version of the kernel named by `--slug`.

On the owner's Windows machine `kaggle datasets create` fails from Git Bash (forward slashes end up
in the upload's temporary file name); run it from PowerShell if a dataset is ever needed.
`kaggle kernels push` works from either shell.
