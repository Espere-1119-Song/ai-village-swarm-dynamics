"""Bayesian online change point detection (Adams and MacKay 2007) with a Normal-Gamma model.

Within a segment the observations are i.i.d. N(mu, 1/lambda), with the conjugate prior
(mu, lambda) ~ NormalGamma(mu0, kappa0, alpha0, beta0); the posterior predictive is a Student t
with 2 alpha degrees of freedom, location mu and squared scale beta (kappa + 1) / (alpha kappa).
The hazard is constant, H = 1 / expected segment length.

`run_length_posterior` returns P(r_t = r | x_1..x_t). Here the run length r counts the
observations of the current segment including x_t, so r = 1 means that x_t opens a new segment
and is scored under the prior predictive. This is the Adams and MacKay recursion (growth with
probability 1 - H, a change with probability H), indexed so that the change-point branch carries
information at time t; with A&M's own indexing P(r_t = 0 | x_1..x_t) equals H for a constant hazard.

`bocpd_changepoints` reads change points off by backtracking the filtered maximum a posteriori run
lengths from the last observation: the run length at T gives the start s of the last segment, the
run length at s - 1 the start of the segment before, and so on. Change points that would leave a
segment shorter than `min_size` are dropped. Each change point carries its support, the posterior
mass of a segment starting within one step of it, evaluated at the end of that segment.
"""

from __future__ import annotations

import numpy as np
from scipy.special import gammaln, logsumexp


def student_t_logpdf(x: float, mu, kappa, alpha, beta) -> np.ndarray:
    """Log predictive density of the Normal-Gamma model at x (vectorised over the parameters)."""
    nu = 2.0 * alpha
    s2 = beta * (kappa + 1.0) / (alpha * kappa)
    return (
        gammaln((nu + 1.0) / 2.0) - gammaln(nu / 2.0) - 0.5 * np.log(nu * np.pi * s2)
        - (nu + 1.0) / 2.0 * np.log1p((x - mu) ** 2 / (nu * s2))
    )


def run_length_posterior(
    x: np.ndarray, hazard: float, mu0: float = 0.0, kappa0: float = 1.0, alpha0: float = 1.0,
    beta0: float = 1.0,
) -> np.ndarray:
    """R[t, r] = P(r_t = r | x_1..x_t) for r = 1..t+1 (column 0 is unused), t = 0..T-1."""
    x = np.asarray(x, dtype=float)
    T = len(x)
    R = np.zeros((T, T + 1))
    if T == 0:
        return R
    lh, l1h = np.log(hazard), np.log1p(-hazard)

    def post(mu, kappa, alpha, beta, xt):
        return ((kappa * mu + xt) / (kappa + 1.0), kappa + 1.0, alpha + 0.5,
                beta + kappa * (xt - mu) ** 2 / (2.0 * (kappa + 1.0)))

    mu, kappa, alpha, beta = (np.atleast_1d(v) for v in post(mu0, kappa0, alpha0, beta0, x[0]))
    log_r = np.array([0.0])  # run lengths 1..t+1 after x_0..x_t
    R[0, 1] = 1.0
    for t in range(1, T):
        xt = x[t]
        grow = log_r + l1h + student_t_logpdf(xt, mu, kappa, alpha, beta)
        new = lh + student_t_logpdf(xt, mu0, kappa0, alpha0, beta0)
        log_r = np.concatenate([[new], grow])
        log_r -= logsumexp(log_r)
        R[t, 1:t + 2] = np.exp(log_r)
        m1, k1, a1, b1 = post(mu, kappa, alpha, beta, xt)
        m0, k0, a0, b0 = post(mu0, kappa0, alpha0, beta0, xt)
        mu, kappa = np.concatenate([[m0], m1]), np.concatenate([[k0], k1])
        alpha, beta = np.concatenate([[a0], a1]), np.concatenate([[b0], b1])
    return R


def bocpd_changepoints(
    x: np.ndarray, hazard: float, min_size: int = 1, **prior: float
) -> tuple[list[int], list[float]]:
    """(change points, support) from the backtracked MAP run lengths; indices start new segments."""
    R = run_length_posterior(x, hazard, **prior)
    T = len(x)
    found: list[tuple[int, float]] = []
    t = T - 1
    while t >= 0:
        r = int(np.argmax(R[t]))
        s = t - r + 1
        if s > 0:
            found.append((s, float(R[t, max(1, r - 1):min(t + 1, r + 1) + 1].sum())))
        t = s - 1
    found.reverse()
    kept: list[tuple[int, float]] = []
    prev = 0
    for s, sup in found:
        if s - prev >= min_size and T - s >= min_size:
            kept.append((s, sup))
            prev = s
    return [s for s, _ in kept], [p for _, p in kept]
