#!/usr/bin/env python3
"""IR (component list + net per pin) -> SPICE netlist that Multisim can import.

    python ir_to_spice.py circuit.ir.json -o circuit.cir

IR shape (see references/ir_schema.json):
{
  "title": "voltage divider",
  "components": [
    {"ref": "V1", "type": "V", "value": "DC 10", "pins": {"1": "in", "2": "0"}},
    {"ref": "R1", "type": "R", "value": "1k",   "pins": {"1": "in", "2": "mid"}},
    {"ref": "R2", "type": "R", "value": "1k",   "pins": {"1": "mid", "2": "0"}}
  ],
  "analysis": {"kind": "tran", "step": "10u", "stop": "5m"}
}

Pin numbers are the SPICE node order: R/C/L/V/I 1->2, D 1=anode 2=cathode,
Q 1=collector 2=base 3=emitter. A component may carry "spice": "<full line
without the ref>" to bypass the template, e.g. {"ref":"X1","spice":"in 0 1 opamp"}.
"""
import argparse
import json
import sys

# type -> (spice letter, number of pins, pin names in order)
TYPES = {
    "R": ("R", 2, "1 2"),
    "C": ("C", 2, "1 2"),
    "L": ("L", 2, "1 2"),
    "V": ("V", 2, "1 2"),
    "I": ("I", 2, "1 2"),
    "D": ("D", 2, "1(anode) 2(cathode)"),
    "Q": ("Q", 3, "1(c) 2(b) 3(e)"),
    "X": ("X", 0, "all pins then subckt name in value"),
}


class IrError(Exception):
    pass


def validate(ir):
    comps = ir.get("components")
    if not isinstance(comps, list) or not comps:
        raise IrError("components: non-empty list required")
    nodes = set(ir.get("nodes") or [])
    refs = set()
    for i, c in enumerate(comps):
        ref = c.get("ref")
        if not ref:
            raise IrError(f"components[{i}]: ref required")
        if ref in refs:
            raise IrError(f"components[{i}]: duplicate ref {ref}")
        refs.add(ref)
        t = c.get("type")
        if t not in TYPES:
            raise IrError(f"{ref}: type must be one of {sorted(TYPES)}, got {t!r}")
        pins = c.get("pins") or {}
        need = TYPES[t][1]
        if need and len(pins) != need:
            raise IrError(f"{ref}: {t} needs {need} pins, got {len(pins)}")
        for p in pins:
            if not str(p).isdigit():
                raise IrError(f"{ref}: pin keys must be digits, got {p!r}")
        for net in pins.values():
            if not isinstance(net, str) or not net:
                raise IrError(f"{ref}: net names must be non-empty strings")
            if nodes and net not in nodes:
                raise IrError(f"{ref}: net {net!r} not declared in nodes")
            if net.upper() == "GND":
                raise IrError(f"{ref}: use net '0' for ground, not 'GND'")
    allnets = {n for c in comps for n in (c.get("pins") or {}).values()}
    if "0" not in allnets:
        raise IrError("no component connects to ground net '0'")
    return comps


def analysis_line(a):
    if not a:
        return None
    kind = a.get("kind")
    if kind == "tran":
        return f".tran {a['step']} {a['stop']}" + (f" {a['start']}" if a.get("start") else "")
    if kind == "ac":
        return f".ac {a.get('sweep', 'dec')} {a['points']} {a['fstart']} {a['fstop']}"
    if kind == "dc":
        return f".dc {a['source']} {a['start']} {a['stop']} {a['step']}"
    if kind == "op":
        return ".op"
    raise IrError(f"analysis.kind must be tran/ac/dc/op, got {kind!r}")


def render(ir):
    comps = validate(ir)
    lines = ["* " + (ir.get("title") or "multisim-build generated netlist")]
    for c in comps:
        ref = c["ref"]
        pins = c.get("pins") or {}
        if "spice" in c:
            lines.append(f"{ref} {c['spice']}")
            continue
        letter, need, _ = TYPES[c["type"]]
        if need:
            nets = " ".join(pins[str(i)] for i in range(1, need + 1))
        else:
            nets = " ".join(pins[k] for k in sorted(pins, key=int))
        value = c.get("value", "")
        parts = [ref, nets, value]
        line = " ".join(p for p in parts if p)
        lines.append(line)
    al = analysis_line(ir.get("analysis"))
    if al:
        lines.append(al)
    lines.append(".end")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ir", help="IR json file")
    ap.add_argument("-o", "--out", help="output .cir (default: stdout)")
    a = ap.parse_args(argv)
    try:
        with open(a.ir, encoding="utf-8") as f:
            ir = json.load(f)
        text = render(ir)
    except (OSError, json.JSONDecodeError, IrError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(text)
        print(f"wrote {a.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
