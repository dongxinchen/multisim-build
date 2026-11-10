#!/usr/bin/env python3
"""Self-check for the multisim-build skill: codec roundtrip + IR -> netlist.

    python tests/test_selfcheck.py

Exit 0 means the shipped scripts still work on this machine.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import pkware  # noqa: E402
import ir_to_spice  # noqa: E402
import ms14_verify  # noqa: E402
import msfind  # noqa: E402


def check_codec():
    xml = (b'<?xml version="1.0" encoding="ASCII"?>\n<MSMElectronicsWorkbench Schema="67">'
           + b"<Item Value='x'/>" * 3000 + b"</MSMElectronicsWorkbench>\n")
    data = pkware.pack_bytes(xml)
    assert data.startswith(pkware.MS14_MAGIC), "container magic missing"
    got = pkware.unpack_bytes(data)
    assert got == xml, "pack/unpack roundtrip mismatch"
    print(f"codec      ok  {len(xml)} -> {len(data)} -> {len(got)} bytes")


def check_spice():
    with open(os.path.join(HERE, "divider.ir.json"), encoding="utf-8") as f:
        ir = json.load(f)
    text = ir_to_spice.render(ir)
    lines = text.strip().splitlines()
    assert lines[0].startswith("* "), "title line missing"
    assert "V1 in 0 DC 10" in lines, lines
    assert "R1 in mid 1k" in lines, lines
    assert "R2 mid 0 1k" in lines, lines
    assert lines[-2] == ".tran 10u 5m", lines
    assert lines[-1] == ".end", lines
    print(f"ir_to_spice ok  {len(lines) - 1} statements")


def check_rejects_bad_ir():
    bad = {"components": [{"ref": "R1", "type": "R", "value": "1k", "pins": {"1": "a", "2": "b"}}]}
    try:
        ir_to_spice.validate(bad)
    except ir_to_spice.IrError as e:
        assert "ground" in str(e), e
        print("validation  ok  rejects IR without ground net")
        return
    raise AssertionError("IR without ground net was accepted")


def check_value_parsing():
    cases = {
        "1k": 1000.0, "1K": 1000.0, "4.7k": 4700.0, "100n": 1e-7,
        "1E-07": 1e-7, "4.7u": 4.7e-6, "2.2M": 2.2e6, "1m": 1e-3,
        "10meg": 10e6, "?": None, "DC 10": None, "LM358": None,
    }
    for text, want in cases.items():
        got = ms14_verify.spice_to_float(text)
        if want is None:
            assert got is None, f"spice_to_float({text!r}) = {got!r}, want None"
        else:
            assert got is not None and abs(got - want) <= abs(want) * 1e-12, \
                f"spice_to_float({text!r}) = {got!r}, want {want!r}"
    print(f"value parse ok  {len(cases)} cases")


def check_verify():
    with open(os.path.join(HERE, "divider.ir.json"), encoding="utf-8") as f:
        divider = json.load(f)
    with open(os.path.join(HERE, "rc_lowpass.dump.json"), encoding="utf-8") as f:
        dump = json.load(f)
    with open(os.path.join(HERE, "rc_lowpass.ir.json"), encoding="utf-8") as f:
        rc = json.load(f)

    problems, notes = ms14_verify.verify(rc, dump)
    assert not problems, f"verify rejected a correct circuit: {problems}"

    # wrong pin net must be caught
    import copy
    bad = copy.deepcopy(rc)
    bad["components"][1]["pins"]["2"] = "mid"
    problems, _ = ms14_verify.verify(bad, dump)
    assert problems and "pin 2" in problems[0], f"wrong net not caught: {problems}"

    # wrong value must be caught
    bad2 = copy.deepcopy(rc)
    bad2["components"][1]["value"] = "2.2k"
    problems, _ = ms14_verify.verify(bad2, dump)
    assert problems and "2200" in problems[0], f"wrong value not caught: {problems}"

    # a different circuit must not pass against this dump
    problems, _ = ms14_verify.verify(divider, dump)
    assert problems, "unrelated IR passed verification"
    print(f"verify      ok  pass/mismatch/unrelated all behave (notes: {len(notes)})")


def check_library():
    rows, kws, aliases = msfind.load()
    assert len(rows) > 30000, f"data pack looks truncated: {len(rows)} components"
    assert len(kws) > 80, f"only {len(kws)} curated keywords"

    # curated keyword path, Chinese
    key, entry = msfind.resolve_keyword("电阻", kws)
    assert entry is not None, "keyword 电阻 not resolved"
    hits = msfind.keyword_hits(entry, rows)
    assert hits, "keyword 电阻 matched nothing"
    assert any("RESISTOR" in r["family"] for _, r in hits), hits[:3]

    # part-number path
    hits = msfind.search("LM358", rows, aliases, limit=5)
    assert hits and any("LM358" in r["component"] for _, r in hits), hits[:3]

    # an instrument keyword must not pretend to be a library component
    key, entry = msfind.resolve_keyword("示波器", kws)
    assert entry is not None and entry.get("instrument"), entry
    assert not entry.get("rules"), "instrument keyword should carry no family rules"
    print(f"library     ok  {len(rows)} components, {len(kws)} keywords, {len(aliases)} aliases")


def check_cli():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "x.cir")
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "ir_to_spice.py"),
                            os.path.join(HERE, "divider.ir.json"), "-o", out],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert os.path.getsize(out) > 0, "empty netlist"
    print("cli         ok  ir_to_spice.py wrote a netlist")


if __name__ == "__main__":
    check_codec()
    check_spice()
    check_rejects_bad_ir()
    check_value_parsing()
    check_verify()
    check_library()
    check_cli()
    print("all checks passed")
