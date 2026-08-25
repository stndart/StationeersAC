"""Demo: pollutant → methane → nitrogen at -180 C, plus an override example."""

from __future__ import annotations

from cascade import StepSpec, run_cascade


def main() -> None:
    print("=== optimized X / CH4 / N2 @ -180 C ===\n")
    r = run_cascade(
        steps=[
            StepSpec(media="X"),
            StepSpec(media="CH4"),
            StepSpec(media="N2"),
        ],
        t_hot_C=40,
        t_target_C=-180,
    )
    print(r.summary())

    print("\n=== same chain, CFHE on CH4 locked to 2 ===\n")
    r2 = run_cascade(
        steps=[
            StepSpec(media="X"),
            StepSpec(media="CH4", n_cfhe=2),
            StepSpec(media="N2"),
        ],
        t_hot_C=40,
        t_target_C=-180,
    )
    print(r2.summary())
    print(
        f"Override delta: Q {r.q_at_target_kj_tick:.3f} -> {r2.q_at_target_kj_tick:.3f} kJ/tick"
    )


if __name__ == "__main__":
    main()
