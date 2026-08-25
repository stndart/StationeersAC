"""Dump Python run_from_body JSON for the JS golden tests.

Run from stationeers-AC:

    python -m cascade.dump_web_fixtures
"""

from __future__ import annotations

import json
from pathlib import Path

from cascade.server import meta, run_from_body

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "src" / "cascade" / "fixtures"

CASES: dict[str, dict] = {
    "default_chain.json": {
        "t_hot_C": 40,
        "t_target_C": -180,
        "dump_radiators": None,
        "steps": [{"media": "X"}, {"media": "CH4"}, {"media": "N2"}],
    },
    "locked_cfhe.json": {
        "t_hot_C": 40,
        "t_target_C": -180,
        "dump_radiators": None,
        "steps": [{"media": "X"}, {"media": "CH4", "n_cfhe": 2}, {"media": "N2"}],
    },
    "infeasible_h2o.json": {
        "t_hot_C": 40,
        "t_target_C": -180,
        "dump_radiators": None,
        "steps": [{"media": "H2O"}],
    },
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in CASES.items():
        payload = {"input": body, "output": run_from_body(body)}
        (OUT / name).write_text(
            json.dumps(payload, allow_nan=False, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {OUT / name}")
    (OUT / "meta.json").write_text(
        json.dumps(meta(), allow_nan=False, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT / 'meta.json'}")


if __name__ == "__main__":
    main()
