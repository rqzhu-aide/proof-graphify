# Stat Proof Check

Version `3.2.1` audits a paper's written mathematical arguments. It records exact claims, source evidence, consequential inferences, independent review, findings, and unresolved limits, then delivers an interactive HTML report. This is a scoped, non-formal examination; a successful database check or report build does not certify a theorem.

## Use

Install this `stat-proof-check/` directory under its existing skill name in a user-wide skill root. From the [repository root](https://github.com/rqzhu-aide/proof-graphify/blob/main/README.md), the validated installer can install it into the Agents and Claude skill directories:

```powershell
python -B tools/install_proofcheck.py --source stat-proof-check --target agents --target claude
```

Use `--upgrade` for an existing installation. Preserve `allow_implicit_invocation: false` and the Claude `"stat-proof-check": "user-invocable-only"` override. Invoke the skill explicitly:

```text
Use $stat-proof-check to audit this theorem and its prerequisite arguments.
```

Choose Triage for mapping suspected issues, Focused for selected results and their necessary prerequisites, or Full for the manuscript and supplied supplements. The [skill instructions](SKILL.md) define scope and the scientific standard. The workflow prepares source evidence and primary examinations, obtains independent review and integrates findings, then renders a frozen result. Proof omissions and unresolved disagreements remain findings; the skill does not silently repair the manuscript's mathematics.

## Outputs and continuation

```text
proof-check-<paper-name>/
  audit.db
  work/
  frozen/summary.json
  report.html
```

Keep the database and frozen artifacts for continuation. Report what was examined and independently reviewed, together with material omissions and source limits. New audits start independently from the manuscript in their own folder and database, including when a Graphify overview already exists. Start with the [database workflow](references/database-audit.md), and use the [controller workflow](references/controller-workflow.md) for continuation commands.

## Runtime and compatibility

This package bundles `paper_core` version `3.2.1` and runs independently of Graphify and the source checkout. Shared Python 3.10+ runs the helpers; Node.js produces the HTML report. Optional offline LaTeX conversion uses shared `latex2mathml`. Install missing dependencies globally or user-wide.

New audits use `coherent-proof-audit/1`, the `coherent-examinations/1` feature, storage format `4`, and record contract `4`. Historical v2 audits retain their original protocol and compatible runtime. See [database compatibility](references/database-compatibility.md), the [implementation boundary](IMPLEMENTATION.md), and the retained [validation record](VALIDATION.md).

[MIT license](LICENSE)
