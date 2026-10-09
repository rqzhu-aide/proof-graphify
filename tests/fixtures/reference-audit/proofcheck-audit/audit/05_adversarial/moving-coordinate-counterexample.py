"""Finite instances of the symbolic moving-coordinate counterexample.

For every fixed j the coordinate is zero whenever n > j, while every row
contains its j=n entry equal to one. These exact identities prove the limits;
the finite instances below only check the declared construction.
"""
for n in (1, 2, 5, 20):
    row = [int(j == n) for j in range(1, n + 1)]
    maximum = max(row)
    estimator_error = maximum
    assert maximum == 1 and estimator_error == 1
    print(f"n={n}: row maximum={maximum}, estimator error={estimator_error}")
print("For each fixed j, X_nj=0 for every n>j; both claimed limits fail.")
