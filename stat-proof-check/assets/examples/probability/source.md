# Worked probability example

This authored teaching fixture demonstrates a recorded proof. Its saved judgments are
worked answers, not the output of a fresh independent mathematical audit.

<!-- begin:setup -->
Let \((X_i,Y_i)_{i=1}^n\) be independent identically distributed pairs with
\(0\le X_i,Y_i\le1\). Dependence between \(X_i\) and \(Y_i\) within a pair is allowed.
Write \(\mu_X=\mathbb E X_i\), \(\mu_Y=\mathbb E Y_i\), and let bars denote sample means.
Take \(0<b\le1\), \(0<\delta<1\), \(n\ge1\), and
\(t=\sqrt{\log(4/\delta)/(2n)}\le b/2\), with \(\mu_Y\ge b\).
Define \(R=\bar X/\bar Y\) when \(\bar Y>0\), and \(R=0\) otherwise.
<!-- end:setup -->

<!-- begin:hoeffding -->
Lemma H (globally stated conditional theorem). For independent \(Z_1,\ldots,Z_n\)
in \([0,1]\), with \(m=n^{-1}\sum_i\mathbb E Z_i\), every \(u>0\) satisfies
\[\Pr\{|\bar Z-m|>u\}\le2\exp(-2nu^2).\]
The hypotheses are part of this theorem's statement; they are not temporary
assumptions confined to the theorem's own proof scope.
<!-- end:hoeffding -->
<!-- begin:hoeffding_proof -->
For a bounded \(Z\), put \(\psi(\lambda)=\log\mathbb E e^{\lambda Z}\).
Differentiation under the expectation is valid by boundedness on compact
\(\lambda\)-intervals. Under the exponentially tilted probability law,
\(\psi''(\lambda)=\operatorname{Var}_\lambda(Z)\le1/4\): variance is no larger
than \(\mathbb E_\lambda(Z-1/2)^2\le1/4\).
Taylor's integral formula gives
\[\psi(\lambda)-\lambda\mathbb EZ
=\lambda^2\int_0^1(1-s)\psi''(s\lambda)\,ds\le\lambda^2/8.\]
Independence and Markov's inequality therefore give, for \(\lambda>0\),
\[\Pr\{\bar Z-m>u\}\le\exp(-n\lambda u+n\lambda^2/8).\]
Choosing \(\lambda=4u\) gives \(\exp(-2nu^2)\). Applying the same centered
moment bound at \(-\lambda\) proves the lower-tail bound. A union bound proves H.
<!-- end:hoeffding_proof -->

<!-- begin:ratio -->
Theorem R. Under the setup above,
\[\Pr\left\{\left|R-\frac{\mu_X}{\mu_Y}\right|
\le\frac{2t}{b}+\frac{2t}{b^2}\right\}\ge1-\delta.\]
Thus the displayed error is at most
\((2/b+2/b^2)\sqrt{\log(4/\delta)/(2n)}\); for fixed \(b\), this has order
\(\sqrt{\log(4/\delta)/n}\) in the stated regime \(t\le b/2\).
<!-- end:ratio -->
<!-- begin:ratio_proof -->
<!-- begin:x_tail -->
Apply H with \(Z_i=X_i\), \(m=\mu_X\), and \(u=t\).
Independence across pairs implies independence of the \(X_i\); boundedness is in the setup.
Then \(\Pr\{|\bar X-\mu_X|>t\}\le2e^{-2nt^2}=\delta/2\).
<!-- end:x_tail -->
<!-- begin:y_tail -->
Apply H separately with \(Z_i=Y_i\), \(m=\mu_Y\), and \(u=t\).
The \(Y_i\) are independent across pairs and bounded. Hence
\(\Pr\{|\bar Y-\mu_Y|>t\}\le\delta/2\).
<!-- end:y_tail -->
<!-- begin:joint -->
Let \(E=\{|\bar X-\mu_X|\le t\}\cap\{|\bar Y-\mu_Y|\le t\}\).
The union bound gives \(\Pr(E^c)\le\delta/2+\delta/2=\delta\).
No independence between these two events is assumed or needed.
<!-- end:joint -->
<!-- begin:event -->
For the next two pointwise calculations, fix an outcome \(\omega\in E\).
This is a temporary proof assumption, not a probability-one assertion.
<!-- end:event -->
<!-- begin:denominator -->
On the fixed outcome in \(E\),
\(\bar Y\ge\mu_Y-t\ge b-t\ge b/2>0\).
<!-- end:denominator -->
<!-- begin:pointwise -->
On that same outcome, \(R=\bar X/\bar Y\), and
\[\left|R-\frac{\mu_X}{\mu_Y}\right|
\le\frac{|\bar X-\mu_X|}{\bar Y}
+\frac{|\mu_X|\,|\mu_Y-\bar Y|}{\bar Y\mu_Y}
\le\frac{2t}{b}+\frac{2t}{b^2},\]
using \(0\le\mu_X\le1\), \(\mu_Y\ge b\), and the denominator bound.
<!-- end:pointwise -->
<!-- begin:conditional -->
The outcome in \(E\) was arbitrary, so the pointwise bound establishes
\(E\subseteq\{|R-\mu_X/\mu_Y|\le2t/b+2t/b^2\}\).
Discharge the temporary assumption \(\omega\in E\); do not assert the bound
unconditionally for every outcome.
<!-- end:conditional -->
<!-- begin:final -->
The event inclusion and \(\Pr(E)\ge1-\delta\) give Theorem R.
Substitution of the specified \(t\) yields the displayed rate and preserves
\(t\le b/2\). The branch \(\bar Y=0\) is defined but lies outside \(E\).
<!-- end:final -->
<!-- end:ratio_proof -->
