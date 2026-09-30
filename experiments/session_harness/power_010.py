"""Card 010 power note: eval tasks x rollouts for a 3-arm paired comparison (standard library only).

Model (per eval task i, r rollouts per arm, every arm on every task):
  D_i = (treatment acceptances - incumbent acceptances) / r
  Var(D_i) = tau2 + (E[p0(1-p0)] + E[p1(1-p1)]) / r,   E[p(1-p)] = pbar(1-pbar) - sigma2
  sigma2 = between-task variance of true acceptance; tau2 = task-by-treatment variance of the true effect.
  n_tasks = (z_{1-alpha/2} + z_{1-beta})^2 * Var(D_i) / delta^2
Two confirmatory comparisons (memory vs incumbent, symbolic vs incumbent), Bonferroni alpha = 0.05 / 2 two-sided,
power 0.80. Runs = n_tasks x r x 3 arms.

Also: the c007 between-task variance (one-way ANOVA on 20 tasks x 2 rollouts) and the empirical per-task
difference variance between c007 (Reticle) and c018 (native Claude Code) on the same 20 tasks.

Usage: python experiments/session_harness/power_010.py
"""
from math import ceil, sqrt
from statistics import NormalDist

Z = NormalDist().inv_cdf


def n_tasks(p0, delta, r, sigma2, tau2, alpha=0.025, power=0.80):
    p1 = p0 + delta
    var = tau2 + ((p0 * (1 - p0) - sigma2) + (p1 * (1 - p1) - sigma2)) / r
    return (Z(1 - alpha / 2) + Z(power)) ** 2 * var / delta ** 2, var


def main():
    # c007 per-task accepted of 2 (card 007 report): 15 x 2/2, 2 x 1/2, 3 x 0/2
    c007 = [2] * 15 + [1] * 2 + [0] * 3
    k, n = 2, len(c007)
    means = [a / k for a in c007]
    grand = sum(means) / n
    msb = k * sum((m - grand) ** 2 for m in means) / (n - 1)
    msw = sum(a * (1 - a / k) ** 2 + (k - a) * (a / k) ** 2 for a in c007) / (n * (k - 1))
    sigma2_c007 = (msb - msw) / k
    icc = (msb - msw) / (msb + (k - 1) * msw)
    print(f"c007: mean {grand:.3f}, MSB {msb:.4f}, MSW {msw:.4f}, between-task variance {sigma2_c007:.4f}, ICC {icc:.2f}")

    # c007 vs c018, per-task accepted of 2 (tally_task_outcomes_010.py), same task order
    tasks = ["001", "002", "022", "023", "024", "025", "032", "033", "034", "040", "042", "043", "044", "046",
             "057", "060", "061", "073", "075", "076"]
    c007_by = dict(zip(tasks, [1, 2, 1, 2, 2, 2, 0, 2, 2, 2, 2, 2, 2, 2, 0, 2, 0, 2, 2, 2]))
    c018_by = dict(zip(tasks, [0, 2, 0, 2, 2, 2, 0, 1, 2, 2, 2, 2, 2, 2, 0, 1, 1, 2, 2, 2]))
    d = [(c018_by[t] - c007_by[t]) / 2 for t in tasks]
    md = sum(d) / len(d)
    vd = sum((x - md) ** 2 for x in d) / (len(d) - 1)
    print(f"c018 - c007 per-task difference: mean {md:+.3f}, variance {vd:.4f} (n=20, r=2)")

    print("\nn_tasks for delta = 0.15, alpha = 0.025 two-sided, power 0.80 (runs = n x r x 3)")
    scenarios = [("optimistic", 0.15, 0.00), ("central", 0.10, 0.02), ("pessimistic", 0.05, 0.04)]
    for p0 in (0.30, 0.45, 0.60):
        for name, s2, t2 in scenarios:
            cells = []
            for r in (2, 3, 4):
                nt, var = n_tasks(p0, 0.15, r, s2, t2)
                cells.append(f"r={r}: Var {var:.4f} n {ceil(nt):3d} runs {ceil(nt) * r * 3:4d}")
            print(f"p0 {p0:.2f} {name:11s} (sigma2 {s2:.2f}, tau2 {t2:.2f}) | " + " | ".join(cells))
    print("\nCentral scenario, p0 = 0.45, other choices:")
    for label, delta, alpha in (("delta 0.15, alpha 0.05 (one primary comparison)", 0.15, 0.05),
                                ("delta 0.20, alpha 0.025", 0.20, 0.025)):
        cells = []
        for r in (2, 3, 4):
            nt, _ = n_tasks(0.45, delta, r, 0.10, 0.02, alpha=alpha)
            cells.append(f"r={r}: n {ceil(nt)} runs {ceil(nt) * r * 3}")
        print(f"  {label}: " + " | ".join(cells))
    print("\nMDE with the stage-1 ceiling (30 eval tasks), central scenario, alpha 0.025:")
    for r in (2, 3, 4):
        var = 0.02 + ((0.45 * 0.55 - 0.10) + (0.525 * 0.475 - 0.10)) / r  # p1 near 0.525 for a ~0.2 effect
        mde = (Z(1 - 0.0125) + Z(0.8)) * sqrt(var / 30)
        print(f"  r={r}: MDE about {mde:.3f}")
    # unpaired reference: two-proportion test per comparison, ignoring task pairing
    p0, p1, a = 0.45, 0.60, 0.025
    pb = (p0 + p1) / 2
    n_arm = (Z(1 - a / 2) * sqrt(2 * pb * (1 - pb)) + Z(0.8) * sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2 / 0.15 ** 2
    print(f"\nUnpaired reference (no task pairing), p0 0.45 -> 0.60, alpha 0.025: {ceil(n_arm)} runs per arm, "
          f"{3 * ceil(n_arm)} in all")


if __name__ == "__main__":
    main()
