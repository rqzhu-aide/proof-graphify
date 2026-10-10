# Proof Graphify architecture

This folder describes the maintained Proof Graphify package and its shared-backend boundary. The [skill](../../proof-graphify/SKILL.md) and [database guide](../../proof-graphify/references/database.md) give operating instructions.

The current skill version is `3.2.1`, with bundled `paper_core` version `3.2.1`. Graphify and Proof Check ship identical common cores and reader components while retaining different scientific workflows.

Read [architecture.md](architecture.md) for the data flow and ownership. Completed plans, audits, and release receipts are kept in the local ignored `archived/` folder, outside the installable skill package.

This repository maintains both independently installable skills, the common source, and the bundle builder. See the [architecture index](../README.md) for ownership and retained change records. Each installed skill runs only its shipped runtime.
