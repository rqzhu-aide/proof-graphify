# Domain-Specific Risk Checks

Read only the sections matching the assigned argument, together with
[mathematical-checking.md](mathematical-checking.md). Record the actual relevant
calculation, conditions, and outcome in the current check's reasoning. These
questions guide scientific examination; they do not require a stored risk row
for every aspect or source line. Record material differences within the coherent
examination; this reference creates no additional required tasks or ledgers.

## Estimated nuisance and algorithm interfaces

Apply this section when the user requests method-to-implementation verification,
the implementation targets a different population quantity, or the paper claims
that its method establishes more than an assumed oracle condition. In database
audits, explain the relevant interface in the affected proof examination or a
deliberately selected global examination.

- Write the exact population target, measure, support, and equality notion.
- Write every fitting-sample law. For a density ratio, write numerator and denominator laws, not labels such as target density and behavior density.
- Identify which marginals are equal, which conditionals change, why any cancellation is valid, and whether domination or positivity and evaluation support hold. Equal reference laws do not require literal reuse of the same finite observations.
- Record the evaluation law or exact evaluation points and the material downstream uses within the declared scope.
- Check whether sample reuse or dependence changes the variance, asymptotic, or finite-sample argument even when it preserves the population target.
- Separate the documented estimator-to-target relation, code-to-documented-estimator relation, code-to-required-target relation, and execution provenance.
- Treat configuration that changes estimator semantics as implementation evidence. Treat revision, run configuration, preprocessing, inputs, and output linkage used to identify a reported run as execution-provenance evidence.
- Check whether regularization, truncation, calibration, constraints, basis selection, or stabilization changes only the finite-sample algorithm, changes the population target, or invalidates the theorem claimed for the implemented estimator.
- If a covariance, eigenvalue, standard-error, or calibration scale may shrink
  with sample size, check whether the implementation imposes a fixed positive
  floor. A fixed floor and a shrinking theoretical scale are different
  asymptotic objects unless their equivalence is proved in the stated regime.
- Verify symmetry and positive semidefiniteness for every estimated covariance
  used in a quadratic form. Verify strict positivity for every calibrated scale
  used as a denominator, or record and analyze the stated degenerate-case rule.
- Quantify the perturbation caused by ridge terms, eigenvalue clipping, positive
  floors, truncation, or other stabilization at the theorem's normalization
  scale. Propagate that error through approximation, studentization, coverage,
  and any claimed limiting distribution.
- If plausible readings change the conclusion, compare their consequences using the relevant manuscript sections. Unresolved ambiguity is a reportable limitation.

## Probability and concentration

- Verify independence, conditioning, filtration, measurability, and tail assumptions.
- Track every event and accumulated failure probability.
- Check whether a fixed-object bound is used uniformly without a finite union, covering, or complexity argument.
- Distinguish expectation, high probability, almost sure, and conditional statements.
- Check random indices, stopping times, and data-dependent classes against theorem prerequisites.

## Asymptotics and empirical processes

- Distinguish `O`, `o`, `O_p`, `o_p`, weak convergence, and almost-sure rates.
- Track hidden constants and uniformity over parameters or distributions.
- Justify stochastic equicontinuity, tightness, measurability, and interchange of limits.
- Check scaling regimes when both sample size and dimension vary.
- Verify that remainder terms are negligible under the theorem's exact regime.

## Optimization and algorithms

- Establish existence before using a minimizer and uniqueness before identifying it.
- Check convexity, smoothness, coercivity, compactness, and constraint qualification.
- Distinguish local, stationary, and global conclusions.
- Verify initialization, step size, stopping criteria, and randomness assumptions.
- Check that an algorithmic iterate is the same object covered by the theorem.

## Matrix and high-dimensional analysis

- Check dimensions, symmetry, definiteness, rank, invertibility, and norm type.
- Distinguish a covariance matrix being positive semidefinite from every
  derived standard-error or calibration scale being strictly positive. Handle
  zero-variance directions explicitly.
- Track condition numbers, eigenvalue gaps, and dimension-dependent constants.
- Verify perturbation theorem prerequisites and matrix inequality ordering.
- Compare any fixed spectral floor or ridge level with the smallest eigenvalue
  scale allowed by the theorem. Bound the stabilization perturbation in the
  norm and normalization used by the final claim.
- Check whether entrywise, Frobenius, spectral, and induced norms are interchanged legally.

## Causal inference and semiparametric theory

- Distinguish identification from estimation and population targets from sample analogues.
- Verify positivity, consistency, exchangeability, and interference assumptions where used.
- Check nuisance-rate products, cross-fitting independence, and influence-function centering.
- Confirm that the stated estimator matches the object analyzed in the expansion.
- Separate model-based, design-based, and randomization-based probability statements.

## Machine-learning theory

- Match the loss, hypothesis class, sampling model, and randomness to the theorem used.
- Check uniform convergence or stability conditions rather than assuming generalization.
- Track optimization error, approximation error, and statistical error separately.
- Verify data dependence in representations, hyperparameters, and model selection.
- Distinguish population guarantees from finite benchmark performance.

## Lower bounds and reductions

- Verify the constructed alternatives belong to the parameter class.
- Check separation, divergence, packing size, and reduction direction.
- Track constants and regimes required by Fano, Le Cam, Assouad, or testing bounds.
- Confirm that a lower bound for one loss or model transfers to the claimed target.

## Analysis and measure theory

- Justify limit, expectation, derivative, integral, supremum, and infimum exchanges.
- Check domination, uniform integrability, compactness, continuity, and measurability.
- Distinguish pointwise, uniform, almost-everywhere, and almost-sure statements.
- Verify nonzero denominators, boundary behavior, and domain closure.
