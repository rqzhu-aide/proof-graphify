> Historical v2 reference retained from the baseline. Its workflow and completion requirements do not govern v3. Use [the v3 workflow](controller-workflow.md) and [graph authoring](graph-records.md).

# Worked probability example

Load this example when learning graph authoring, joint probability reasoning, or
scope discharge. It is not routine worker context. The
[builder](../assets/examples/probability/build_example.py) and
[source](../assets/examples/probability/source.md) are one executable fixture,
including saved primary responses. They use the public database APIs and do not
depend on the repository's test helpers.

Run with a shared Python installation from the [chosen work folder](database-audit.md#choose-the-work-folder).
Use a new supporting-fixture directory under `work/authoring/`:

```text
python -X utf8 -B "<skill-root>/assets/examples/probability/build_example.py" --out work/authoring/probability-example-1 --render
```

Omit `--render` to build only the SQLite database, captured source, response and
submission files, and receipt. Existing nonempty output directories are refused.
The optional report uses the installed renderer and its existing dependencies.
The builder creates its own `probability.db`, `working.html` (when rendered), source,
responses and receipt inside that fixture directory. These illustrate the interface; they
are separate from the paper audit's root `audit.db` and `report.html`.
A later fixture run needs a new directory name.

The saved reasoning is an authored worked answer. The database has no reviewer
qualification or independent response. It requires independent review, so its
report remains a working result and its process is incomplete. Running this
fixture is not a fresh scientific evaluation or evidence of proof-checking accuracy, and it
cannot qualify an independent reviewer.

## Continue through independent review

The example remains deliberately incomplete. For a real paper audit, use its own `audit.db`,
not the fixture's synthetic records. Continue in this order:

1. [Qualify the actual reviewer and record its ID in the audit configuration](database-qualification.md).
2. [Prepare, dispatch and submit independent work](controller-workflow.md); that reference also covers recovery.
3. [Map source targets when needed](review-mapping.md).
4. [Reconcile the actual opinions](reconciler.md), then follow the audit's
   [report and release instructions](database-audit.md#report-and-release).

## The mathematical argument

The source assumes independent identically distributed pairs
\((X_i,Y_i)\in[0,1]^2\), allows dependence within each pair, and sets
\(\mu_Y\ge b>0\). For \(0<\delta<1\), let

\[
t=\sqrt{\frac{\log(4/\delta)}{2n}}\le\frac b2.
\]

Define \(R=\bar X/\bar Y\) when \(\bar Y>0\), and \(R=0\) otherwise.
The source first proves a globally stated conditional Hoeffding lemma using a
bounded tilted variance, a moment-generating-function bound, independence,
Markov's inequality, and two tails. Its proof is included; the example does not
pretend that remembering an external citation verifies that citation.

The ratio argument records these distinct transitions:

1. Apply the lemma to \(X_i\), obtaining failure probability \(\delta/2\).
2. Apply it to \(Y_i\), again obtaining \(\delta/2\).
3. Combine the events by a union bound, so their intersection \(E\) has probability at least \(1-\delta\). Independence of these events is unnecessary.
4. Temporarily fix an outcome in \(E\), giving \(\bar Y\ge\mu_Y-t\ge b/2>0\).
5. On that outcome, calculate

\[
\left|R-\frac{\mu_X}{\mu_Y}\right|
\le\frac{|\bar X-\mu_X|}{\bar Y}
+\frac{|\mu_X|\,|\mu_Y-\bar Y|}{\bar Y\mu_Y}
\le\frac{2t}{b}+\frac{2t}{b^2}.
\]

6. Discharge the arbitrary outcome assumption to obtain an event inclusion.
7. Combine that inclusion with \(\Pr(E)\ge1-\delta\), then substitute \(t\) to obtain the rate while retaining \(t\le b/2\).

The graph has separate concentration applications, the joint event, denominator
bound, pointwise ratio bound, conditional event inclusion, and final composition.
Routine algebra within a step stays together. This is a modeling example, not a
required node count for other proofs.

## Two different uses of assumptions

Lemma H is globally stated with hypotheses inside its assertion. Its applications
explicitly verify boundedness, independence, the mean, and the chosen threshold.
The lemma is available within the consumer's proof context; its hypotheses are
not misrepresented as assumptions trapped in a sibling proof scope.
The two applications save their substitutions explicitly, including `Z_i`, `m`, and `u`.
Their recorded reasoning checks independence across pairs, coordinate boundedness, and `t>0`
locally in Theorem R's setup. The receipt's `specialization_examples` reports availability of
the conditional theorem, both checked applications, and both specialized tail bounds.

By contrast, `scp_event` contains the temporary premise \(\omega\in E\).
The premise and denominator bound are available there and unavailable outside it.
The explicit scope-discharge examination establishes the globally usable
conditional event inclusion. It does not make the denominator bound hold for
every outcome. The receipt reports all six scope probes, including these two
deliberately unavailable outside-scope uses.
The regression tests also deny support when a specialization's applicability check has a gap
or when the supplier is mistakenly restricted to the temporary event scope. A supported general
theorem does not excuse an unchecked hypothesis at a particular use.

The database retains complete source boundaries and exact target specifications.
Each application and derivation has saved reasoning, and composition links the
whole proof to its coverage record. The same fixture can support rendering,
interrupted-work, and selective-renewal tests without introducing another graph
format or manufacturing independent-review credit.
