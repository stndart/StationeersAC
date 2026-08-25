"""Stdlib HTTP API for the cascade constructor. Run from stationeers-AC:

    python -m cascade.server
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from cascade.chain import run_cascade
from cascade.constants import (
    DEFAULT_HX_LOOP_KPA,
    DEFAULT_LIQUID_PIPE_L,
    DUMP_RAD_DT_K,
    EVAP_TARGET_L,
    LIQUID_FEED_L_PER_TICK,
    MAX_CFHE,
    P_MAX_LIQUID_KPA,
)
from cascade.gases import GASES
from cascade.models import StepSpec
from cascade.physics import c_from_k
from cascade.plant import plant_from_result

HOST = "127.0.0.1"
PORT = 8765

_INT_FIELDS = ("n_cfhe", "n_evap_chambers", "n_cond_chambers")
_FLOAT_FIELDS = (
    "p_cond_kPa",
    "p_evap_kPa",
    "t_cond_C",
    "t_evap_C",
    "t_hot_C",
    "t_cold_C",
    "inventory_mol",
    "hx_hot_kPa",
    "hx_cold_kPa",
    "liquid_pipe_L",
)

LOCKABLE_FIELDS = [
    {"key": "t_cond_C", "label": "Condenser temperature", "type": "float", "unit": "C"},
    {"key": "p_cond_kPa", "label": "Condenser pressure", "type": "float", "unit": "kPa"},
    {"key": "t_evap_C", "label": "Evaporator temperature", "type": "float", "unit": "C"},
    {"key": "p_evap_kPa", "label": "Evaporator pressure", "type": "float", "unit": "kPa"},
    {"key": "t_hot_C", "label": "Hot port temperature", "type": "float", "unit": "C"},
    {"key": "t_cold_C", "label": "Cold port temperature", "type": "float", "unit": "C"},
    {"key": "n_cfhe", "label": "CFHE count", "type": "int", "unit": ""},
    {"key": "inventory_mol", "label": "Inventory", "type": "float", "unit": "mol"},
    {"key": "n_evap_chambers", "label": "Evaporator chambers", "type": "int", "unit": ""},
    {"key": "n_cond_chambers", "label": "Condenser chambers", "type": "int", "unit": ""},
    {"key": "hx_hot_kPa", "label": "Hot HX loop pressure", "type": "float", "unit": "kPa"},
    {"key": "hx_cold_kPa", "label": "Cold HX loop pressure", "type": "float", "unit": "kPa"},
    {"key": "liquid_pipe_L", "label": "Liquid pipe volume", "type": "float", "unit": "L"},
]


def _gas_meta() -> list[dict[str, Any]]:
    out = []
    for gas in GASES.values():
        out.append(
            {
                "symbol": gas.symbol,
                "name": gas.name,
                "can_refrigerate": gas.can_refrigerate(),
                "t_freeze_C": None if gas.t_freeze is None else round(c_from_k(gas.t_freeze), 2),
                "t_crit_C": None if gas.t_crit is None else round(c_from_k(gas.t_crit), 2),
                "notes": gas.notes,
            }
        )
    return out


def meta() -> dict[str, Any]:
    return {
        "gases": _gas_meta(),
        "lockable_fields": LOCKABLE_FIELDS,
        "defaults": {
            "max_cfhe": MAX_CFHE,
            "dump_p_kPa": DEFAULT_HX_LOOP_KPA,
            "hx_loop_kPa": DEFAULT_HX_LOOP_KPA,
            "evap_target_L": EVAP_TARGET_L,
            "liquid_feed_L_per_tick": LIQUID_FEED_L_PER_TICK,
            "liquid_pipe_L": DEFAULT_LIQUID_PIPE_L,
            "dump_rad_dt_K": DUMP_RAD_DT_K,
            "p_max_liquid_kPa": P_MAX_LIQUID_KPA,
            "t_hot_C": 40.0,
            "t_target_C": -180.0,
            "preset_steps": [{"media": "X"}, {"media": "CH4"}, {"media": "N2"}],
        },
    }


def _as_number(val: Any, kind: str) -> float | int | None:
    if val is None or val == "":
        return None
    if kind == "int":
        return int(val)
    return float(val)


def spec_from_dict(d: dict[str, Any]) -> StepSpec:
    if not d.get("media"):
        raise ValueError("each step needs media")
    kwargs: dict[str, Any] = {"media": str(d["media"])}
    for k in _INT_FIELDS:
        if k in d:
            kwargs[k] = _as_number(d[k], "int")
    for k in _FLOAT_FIELDS:
        if k in d:
            kwargs[k] = _as_number(d[k], "float")
    return StepSpec(**kwargs)


def run_from_body(body: dict[str, Any]) -> dict[str, Any]:
    steps_raw = body.get("steps") or []
    if not steps_raw:
        raise ValueError("need at least one step")
    specs = [spec_from_dict(s) for s in steps_raw]
    t_hot = float(body["t_hot_C"])
    t_target = float(body["t_target_C"])
    dump = body.get("dump_radiators")
    dump_n = None if dump is None or dump == "" else int(dump)
    result = run_cascade(specs, t_hot, t_target, dump_radiators=dump_n)
    payload = result.to_dict()
    payload["plant"] = plant_from_result(result)
    return payload


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, allow_nan=False, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/api/meta":
            self._json(200, meta())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path != "/api/run":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            self._json(200, run_from_body(body))
        except (ValueError, KeyError, TypeError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:
            self._json(500, {"error": str(e), "trace": traceback.format_exc()})


def main(host: str = HOST, port: int = PORT) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"cascade API http://{host}:{port}  (GET /api/meta, POST /api/run)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        httpd.server_close()


if __name__ == "__main__":
    main()
