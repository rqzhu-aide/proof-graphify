# Repository consolidation, version 3.2.0

Completed locally on 9 October 2026. Both skills and the common core now use version `3.2.0`.

The Proof Graphify repository contains two independently installable packages, `proof-graphify/` and `stat-proof-check/`. The common source, bundle builder, Proof Check installer, compatibility tests and fixtures, and architecture records moved into this repository. Graphify's architecture is under `architecture/proof-graphify/`. The repository root is no longer an installable skill.

The Stat Paper Skills repository retains `stat-write-style`, `stat-paper-review`, and `stat-proof-write`. It no longer contains the maintained Proof Check package or common core. Ignored local archives remain historical backups. Both repositories' READMEs and the individual skill guides describe the new ownership and installation paths.

All 772 pre-existing source and fixture files were backed up and verified byte-for-byte immediately after the moves. The 58 files belonging to the three remaining skills are unchanged. All 67 common-core files are unchanged except for `CORE_VERSION`, which moved from 3.1.0 to 3.2.0. Database formats, protocols, workflow depth, review requirements and stored evidence semantics are unchanged. Historical release and protocol identifiers remain historical.

The canonical builder now generates both bundles within this repository. They have identical manifests and source identity `dfc8c5b3041989dc8540253508443e0f51ed5ff590a6fd576b7863c920c0190d`. Each installed skill imports only its own bundled runtime; test installations use separate parent directories with no sibling skill available.

| Validation | Result |
|---|---|
| Graphify full suite | 435 tests, successful; one Windows symlink skip |
| Proof Check current v3 suite | 277 tests, successful; one Windows symlink subtest skip |
| Storage, overview, native migration and packaging | 213 tests, successful; one Windows symlink skip |
| Release surfaces, math, publication and legacy HTML | 67 tests passed |
| Builder and installer fixtures | 29 tests passed; no real installation |
| Independent relocation packaging checks | 54 tests, successful; one Windows symlink skip |
| Skill metadata and current documentation links | Passed |

The independent checks overlap the larger suites and should not be added as distinct test coverage. Test reports record the new imported paths and the common 3.2.0 identity. Existing user-wide Python and Node were used; no project-local environment was created.

The test reviewer also exercised older audit lanes outside the current release gates. Their legacy classification map has two existing drift failures, and 36 of 49 broad migration tests use historical audit fixtures incompatible with the current coherent contract. Those tests and fixtures were preserved. The selected native-overview migration cases and the complete current v3 audit lane above pass; this relocation does not revise historical audit semantics to make every retained test executable under v3.

Local move receipts, original hashes, test logs and the release manifest are under `../../tmp/repository-consolidation-320/`. This operation did not install either skill, commit, push, or alter Git remotes. It did not perform a new browser review or a new scientific audit.
