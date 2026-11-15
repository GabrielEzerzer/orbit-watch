# Comment-ban lint pack

To adopt the pack, copy this folder into the repo as `setup/lint/`, run `python setup/lint/ratchet --init` from the repo root to write `.lint-baseline.json` with today's counts, commit both, and add the step below to a job on `ubuntu-latest` after `actions/checkout`. The ratchet runs ast-grep 0.51.1 with the rules in `rules/` on every Python, JavaScript, TypeScript and Rust file that `git ls-files` lists, tracked or untracked but not ignored, dot-folders included. A file with no extension is scanned when any word of its shebang names `python`, `uv`, `pipx`, `hatch`, `pdm`, `node`, `deno`, `bun`, `ts-node` or `tsx`. It also fails on any `ast-grep-ignore` comment because ast-grep would otherwise hide matches on that line. Vue, Svelte, Astro and MDX files are not scanned.

The ratchet exits 0 on pass and 1 when a file has more violations than its baseline count or a new file has any. It exits 2 when git or ast-grep could not run, when a file is not valid UTF-8 or ast-grep did not parse it, or when the baseline holds anything but non-negative integer counts. With `--base <ref>` it also reads `.lint-baseline.json` at that ref and exits 1 when any count rose against it; a ref with no baseline passes. A file's counts move only along a rename that git detects, and only to that rename's target; deleting a file frees none of its counts. Make the rename with `git mv`, or stage both sides of it, then run `python setup/lint/ratchet --update`, which lowers the baseline after a cleanup and moves the counts of renamed files but refuses to raise anything else. `--update` and the plain run look for renames since the commit that last changed the baseline, and `--base` looks for them between the ref and the working tree. Committed generated files go in the `ignores` list of each rule for their language, as globs relative to the repo root; Next.js's `next-env.d.ts` is already there. The tests run with `python -m unittest discover -s setup/lint/tests` and need `git` and `ast-grep` on `PATH`.

```yaml
      - name: Comment-ban lint
        env:
          BASE: ${{ github.event.repository.default_branch }}
        run: |
          git fetch --no-tags --depth=1 origin "+refs/heads/$BASE:refs/remotes/origin/$BASE"
          python3 -m venv "$RUNNER_TEMP/lint"
          "$RUNNER_TEMP/lint/bin/pip" install --quiet ast-grep-cli==0.51.1
          PATH="$RUNNER_TEMP/lint/bin:$PATH" python3 setup/lint/ratchet --base "origin/$BASE"
```
