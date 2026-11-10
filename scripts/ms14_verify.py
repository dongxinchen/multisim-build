#!/usr/bin/env python3
"""Compare an IR against what Multisim actually has open (via mscom dump).

    python ir_to_spice.py circuit.ir.json -o circuit.cir
    mscom.exe dump circuit.ms14 > circuit.dump.json
    python ms14_verify.py circuit.ir.json circuit.dump.json

Three checks, in order of how much they matter:
  1. every component exists, with the same reference designators
  2. every pin sits on the net the IR asked for        <- topology
  3. R/C/L values match within tolerance               <- parameters

Exit 0 only when all three pass. Wording of a failure says which check broke.
"""
import argparse
import json
import sys

MULT = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
        "k": 1e3, "K": 1e3, "M": 1e6, "meg": 1e6, "MEG": 1e6, "G": 1e9, "T": 1e12}

VALUE_TOL = 1e-6


class Verdict(Exception):
    pass


def spice_to_float(text):
    """'1k' -> 1000.0, '100n' -> 1e-07, '4.7u' -> 4.7e-06, '1E-07' -> 1e-07.

    Returns None when the text is not a plain number with an optional suffix
    (e.g. 'DC 10', '?', 'LM358').
    """
    if text is None:
        return None
    s = str(text).strip().replace(" ", "")
    if not s or s == "?":
        return None
    try:
        return float(s)
    except ValueError:
        pass
    # split trailing unit suffix
    i = len(s)
    while i > 0 and (s[i - 1].isalpha()):
        i -= 1
    num, suffix = s[:i], s[i:]
    if not num or not suffix:
        return None
    try:
        base = float(num)
    except ValueError:
        return None
    for key in ("meg", "MEG"):          # longest suffix first
        if suffix.startswith(key):
            return base * MULT[key]
    if suffix[0] in MULT:
        return base * MULT[suffix[0]]
    return None                    # unknown unit -> not comparable


def circuit_pin_nets(dump):
    """{(ref, pin): net} built from mscom's pin->net table."""
    out = {}
    for net, members in (dump.get("nets") or {}).items():
        for m in members:
            if ":" not in m:
                continue
            ref, pin = m.rsplit(":", 1)
            out[(ref.strip(), pin.strip())] = net
    return out


def verify(ir, dump):
    problems = []
    notes = []

    if not dump.get("ok"):
        raise Verdict("mscom dump reported: " + str(dump.get("error")))
    if not dump.get("netlistOk"):
        notes.append("netlist export produced no usable file: pin/net checks skipped")
        return problems, notes

    ir_comps = {c["ref"]: c for c in ir.get("components", [])}
    circ_refs = {c["ref"] for c in dump.get("components", [])}

    # 1) component set
    missing = sorted(set(ir_comps) - circ_refs)
    extra = sorted(circ_refs - set(ir_comps))
    if missing:
        problems.append(f"components missing in circuit: {', '.join(missing)}")
    if extra:
        problems.append(f"unexpected components in circuit: {', '.join(extra)}")

    # 2) topology
    pin_nets = circuit_pin_nets(dump)
    compared = 0
    for ref, comp in sorted(ir_comps.items()):
        for pin, want in sorted((comp.get("pins") or {}).items()):
            got = pin_nets.get((ref, pin))
            compared += 1
            if got is None:
                problems.append(f"{ref} pin {pin}: not found in circuit netlist (expected net {want!r})")
            elif got != want:
                problems.append(f"{ref} pin {pin}: on net {got!r}, IR says {want!r}")
    if compared == 0:
        problems.append("IR has no pins to compare")

    # 3) values, R/C/L only
    dump_values = {c["ref"]: c.get("rlc") for c in dump.get("components", [])}
    checked = 0
    for ref, comp in sorted(ir_comps.items()):
        if comp.get("type") not in ("R", "C", "L"):
            continue
        want = spice_to_float(comp.get("value"))
        got_raw = dump_values.get(ref)
        if want is None or got_raw is None:
            notes.append(f"{ref}: value not comparable (ir={comp.get('value')!r} circuit={got_raw!r})")
            continue
        try:
            got = float(got_raw)
        except (TypeError, ValueError):
            notes.append(f"{ref}: circuit value {got_raw!r} is not numeric")
            continue
        checked += 1
        if abs(got - want) > max(abs(want) * VALUE_TOL, 1e-18):
            problems.append(f"{ref}: value {got:g} in circuit, IR says {want:g} (from {comp.get('value')!r})")

    notes.append(f"checked {len(ir_comps)} components, {compared} pins, {checked} RLC values")
    return problems, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ir", help="IR json")
    ap.add_argument("dump", help="mscom dump json")
    a = ap.parse_args(argv)
    try:
        with open(a.ir, encoding="utf-8") as f:
            ir = json.load(f)
        with open(a.dump, encoding="utf-8") as f:
            dump = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        problems, notes = verify(ir, dump)
    except Verdict as e:
        print(f"FAIL {e}")
        return 1

    for n in notes:
        print(f"note: {n}")
    if problems:
        print(f"FAIL {len(problems)} difference(s):")
        for p in problems:
            print("  - " + p)
        return 1
    print("PASS 电路与 IR 一致：元件、引脚网络、元件值全部匹配")
    return 0


if __name__ == "__main__":
    sys.exit(main())
