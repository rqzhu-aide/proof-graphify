# Offline release pilot

See [release-evaluation.md](../references/release-evaluation.md) for commands, blinding, rationale assessment, usage recording, and comparison limitations.

All eighteen problems and their candidate keys are provisional pending actual statistical-theory expert review. No live checker performance is included in this directory. Unit-test responses are synthetic and do not establish model accuracy.

Only generated `packets/` files are checker-visible. Keep `catalog.json`, `keys/`, both rubric files, prospective allocation, coordinator manifests, and prior responses out of checking contexts. Development and held-out splits keep complete correct/flawed pairs together. New preparations use allocation v2, which records known exposures and moves q-52fd to development. The historical v1 catalog, keys, and scores remain unchanged; the remaining held-out designation does not establish absence of exposure.

Scorer v2 adds false-establishment diagnostics and preserves v1 interpretation for old records. Software tests verify these mechanics. Expert adjudication, replacement unseen material, and matched live-workflow cost and quality comparisons remain separate unfinished empirical work.

The harness uses the standard library and the existing shared Python installation. It contains no model API client, package installer, or project-local environment.
