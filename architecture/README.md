# Proof Graphify architecture

This folder describes the maintained Proof Graphify package and its shared-backend boundary. The [skill](../SKILL.md) and [database guide](../references/database.md) give operating instructions.

The current skill version is `3.1.10`, with shared `paper_core` version `2.3.5`.

Read [architecture.md](architecture.md) for the data flow and ownership. Completed plans, audits, and release receipts are kept in the local ignored `archived/` folder, outside the installable skill package.

For cross-package development, this repository can sit beside `../stat-paper-skills/`. Each sibling has its own Git root and remote; the installed skill needs neither sibling checkout nor network access.
