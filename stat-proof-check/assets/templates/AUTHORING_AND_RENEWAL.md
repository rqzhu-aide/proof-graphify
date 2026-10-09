# Compact authoring and renewal examples

Read only the section needed. Start from `annotation-scaffold`; these excerpts
do not supply mathematical judgments or replace the primary protocol.

## Exact source anchors

Retrieve authenticated text without copying source hashes by hand:

```text
python "<skill-root>/scripts/proofcheck.py" source-lookup "<unit.skeleton.json>" --part statement --lines 10 20
python "<skill-root>/scripts/proofcheck.py" source-lookup "<unit.skeleton.json>" --part proof --annotations "<unit.annotations.json>" --step-key center-score
python "<skill-root>/scripts/proofcheck.py" source-lookup "<unit.skeleton.json>" --packet "<primary-packet.json>" --reference eq:variance
```

Choose the actual range, draft key, or label. Reference lookup also accepts an
occurrence ID. Proof `--lines` selects coverage positions; returned locations
retain original physical files and lines, including included sources. Statement
`--lines` selects physical lines within a locked span. The reviewer decides what
the excerpt establishes and how it is used; lookup supplies no judgment.

Draft step lookup needs current source and obligation bindings, a unique key,
and valid source groups and ranges. Review fields may still be unfinished in
the requested step or elsewhere in the draft. Compilation and submission
continue to require the complete mathematical review.

An obligation input resolves one scalar fact in the normalized contract. For
example, if `/hypotheses/0` records that $x$ is real and the first locked statement
span actually supplies that fact:

```json
{
  "kind": "obligation",
  "reference": "/hypotheses/0",
  "role": "fact",
  "evidence": "The first statement span restricts the arbitrary x to the real numbers.",
  "anchor": {"kind": "statement_span", "index": 1}
}
```

The anchor index is one-based; `/hypotheses/0` is an ordinary zero-based JSON
Pointer. Use `context_span` for a fact in `obligation.context_spans`. Each such
locked span also requires a substantive `role`, such as "Defines the ambient
probability law used by this proof." Anchor kinds are not `statement` or
`context`. Keep the source span's actual file, lines and hash. A target conclusion
is never an assumed premise. Prior moves and dependencies use their own input
forms, including the [exact result-reuse example](INTERNAL_RESULT_REUSE.md).

Normalization `regime` accepts `finite_sample`, `asymptotic`, `both`,
`not_applicable`, or `unclear`; `uniformity` accepts `pointwise`, `uniform`,
`mixed`, `not_applicable`, or `unclear`. Choose from the paper's meaning and
complete the matching normalization check. Absence and uncertainty do not
supply missing mathematical evidence.

When several atomic moves share a display, keep its exact source grouping and
make each move's `literal`, goal and evidence identify that particular inference
and source objects. Repeating the whole display for every move does not explain
their distinct roles. Retain the existing compact `not_applicable_basis`
shorthand only for genuinely inapplicable risks; it does not replace local
evidence for applicable risks.

For a direct consequence stated after a proof, keep the exact formal statement
anchor and add the consequence's own authenticated span to
`obligation.statement_spans`. Give it a separate conclusion, its actual
`source_spans`, and a faithful `reader_description`, such as "Post-proof equality
case". Its support may use the preceding checked moves when they establish that
assertion. Otherwise record the missing or separate argument honestly. Do not
enlarge the formal statement/proof boundary or invent another theorem heading.
When statement spans lie outside the extracted proof range, explain their
relationship in `source.separate_statement_reason`.

For example, a formal statement at lines 10-20, proof at 30-50, and direct
consequence at 52 keeps both statement spans 10-20 and 52, with proof 30-50.
The extra conclusion must be normalized and independently checked just like
the formal conclusions. These are example coordinates; use the actual source.

## A statement-labeled equation used later in its proof

Consider this source pattern:

```latex
\begin{theorem}
For every real $x$,
\begin{equation}\label{eq:double}
  2x=x+x.
\end{equation}
Moreover, $|2x|\leq 2|x|$.
\end{theorem}
\begin{proof}
Distributivity gives $2x=(1+1)x=x+x$.
Using \eqref{eq:double}, the triangle inequality gives
$|2x|=|x+x|\leq |x|+|x|=2|x|$.
\end{proof}
```

Normalize the identity as its own conclusion, with an exact source span
containing the active label. Its support is the distributivity move inside
the proof. The later triangle-inequality move consumes that earlier move's
exact identity through a `prior_step` premise, with the equation occurrence
and label recorded. The label locates the conclusion; the checked earlier
move establishes it. The statement is never its own premise.

The shared validator accepts either a label inside the earlier proof step or
this exact conclusion-to-support mapping. If one labeled display contains
two conclusions, record each consumed conclusion and its own support. A
different claim, unsupported conclusion, or future move cannot supply the
reference.

Use `own_result_identification` for a proof header or reviewed closing
identification of the result itself. It is not a default for equations owned
by that result. An occurrence that only locates an expression being named can
have an occurrence-specific non-premise explanation; any bound or identity
used afterward still needs its actual proved support. The current primary
readiness check also reconciles these roles and exact dependency uses against
the canonical source inventory.

## File-based commands on Windows

Write larger authoring programs as UTF-8 files outside the audit root, using
normal file editing or bounded chunks. Run the saved file through the shared
Python installation. Do not pass an entire large program as one command-line
argument. Keep LaTeX backslashes escaped in JSON strings.
When a Python authoring program writes mathematical prose, use raw strings
for the LaTeX and serialize JSON normally, for example
`json.dumps({"reason": r"The threshold is $\beta n$."})`. Ordinary Python
strings can turn `\b`, `\t` or `\r` into control characters. Read back the
generated mathematical prose before binding it; never repair only its HTML view.

Submit reviewed annotations through the supported command:

```python
import subprocess
import sys

# Define these as the actual paths for this audit, outside command text.
common = [sys.executable, "-B", str(skill_script)]
subprocess.run(common + [
    "submit-unit", str(skeleton), "--annotations", str(annotations),
    "--packet", str(packet),
], check=True)
```

Arguments containing spaces remain single arguments. An unexpected nonzero exit
must stop dependent actions. A receipt-writing wrapper may save the completed
process's output first, then call `check_returncode()`. Do not continue to a
binding command when writing or validating its new artifact failed. Use the
documented CLI; private implementation helpers are not an authoring interface.

## Renew an existing ledger

For `theorem-renewal-01.skeleton.json`, compilation accepts only the sibling
`theorem-renewal-01.ledger.json`. The filename may change; retain the original
`unit_id`. Compilation never overwrites evidence. A completed ledger with its
judgments cleared or renamed is not a fresh extracted skeleton.

1. Preserve the prior ledger, skeleton and annotations as byte-exact history.
   Keep the old ledger live: existing issues may need it as their origin.
   Retain its complete `independent_check` and every referenced artifact.
   Archive the old skeleton so there will be exactly one live skeleton for the
   unit. Do not remove the ledger before generating its replacement.
2. Run `extract` again using the reviewed source and complete statement/proof
   spans. Use a new unused basename in the same canonical directory, such as
   `theorem-renewal-01.skeleton.json`, and the unchanged unit ID. Normalize the
   genuinely fresh skeleton against the current source. Retain a normalized
   contract only after checking its identity and meaning.
3. Generate the current primary packet with `packet --mode primary --for-recompile`.
   This explicitly binds the unique fresh skeleton while retaining the old
   ledger for issue evidence. Ordinary packets continue to select the ledger;
   the flag is not available for challenge packets. Under unchanged calibration, recheck
   every affected judgment before `rebind-annotations`. Changed calibration
   requires a new scaffold and full judgment review. Keep packets and annotations
   outside the canonical root.
4. Run `submit-unit` to validate and publish the exact new canonical sibling;
   manual `annotation-check` and `compile-annotations` remain supported.
   If compilation fails, keep the old ledger live and inspect the error. Only
   after successful compilation, archive the old ledger before another packet,
   status or validation command, leaving exactly one live ledger for the unit.
   Stop immediately if that archive step fails; preserve both copies for recovery.
   Restore the prior ledger's complete `independent_check` without altering any original
   response or artifact. Retained challenge bindings may now be stale. The next
   primary-readiness check validates primary freshness without demanding that
   those independent bindings already be renewed.
5. Complete primary/issue closure and pass `issues --before-challenge`. Renew
   affected independent review through `record-challenge` and `submit-reconciliation`
   as specified in the [challenge protocol](../../references/challenge-protocol.md).
   Preserved old references allow the new initial artifact to retain
   `superseded_review`. After reconciliation and binding, run
   `ledger-check "<unit.ledger.json>" --final` because the compiled ledger was
   edited. Resolve all final errors, run the audit-wide final gates, and reseal
   only when current.

Rebinding alone never certifies a recheck. Pure operational drift does not
require this renewal, and unchanged mathematical inputs do not justify a claim
of fresh independent review.
