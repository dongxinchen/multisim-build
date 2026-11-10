#!/usr/bin/env python3
"""ms14 / .ewprj container tool: unpack to XML, pack XML back.

    python ms14.py info   design.ms14
    python ms14.py unpack design.ms14 -o design.xml
    python ms14.py pack   design.xml -o design.ms14
    python ms14.py pack   design.xml -o out.ewprj --magic ewprj

Requires only pkware.py in the same directory (pure Python, no deps).
"""
import argparse
import sys

import pkware

MAGICS = {"ms14": pkware.MS14_MAGIC, "ewprj": pkware.EWPRJ_MAGIC}


def cmd_info(path):
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(pkware.MS14_MAGIC):
        magic, name = pkware.MS14_MAGIC, "ms14 (Multisim 10-19)"
    elif data.startswith(pkware.EWPRJ_MAGIC):
        magic, name = pkware.EWPRJ_MAGIC, "ewprj (Electronics Workbench / Ultiboard)"
    else:
        print(f"unknown container, first 36 bytes: {data[:36]!r}")
        return 1
    pos = len(magic)
    total = int.from_bytes(data[pos:pos + 8], "little")
    pos += 8
    print(f"format : {name}")
    print(f"file   : {len(data)} bytes")
    print(f"xml    : {total} bytes uncompressed")
    i = 0
    while pos + 8 <= len(data) and i * 0 < total:
        raw = int.from_bytes(data[pos:pos + 4], "little")
        comp = int.from_bytes(data[pos + 4:pos + 8], "little")
        pos += 8
        if raw == 0 and comp == 0:
            break
        print(f"block {i}: raw={raw} comp={comp} payload_at={pos}")
        pos += comp
        i += 1
        if pos >= len(data):
            break
    print(f"blocks : {i}")
    return 0


def cmd_unpack(path, out):
    xml = pkware.unpack_file(path)
    out = out or (path + ".xml")
    with open(out, "wb") as f:
        f.write(xml)
    print(f"{len(xml)} bytes -> {out}")
    return 0


def cmd_pack(path, out, magic_key):
    with open(path, "rb") as f:
        xml = f.read()
    data = pkware.pack_bytes(xml, MAGICS[magic_key])
    with open(out, "wb") as f:
        f.write(data)
    print(f"{len(xml)} bytes -> {out} ({len(data)} bytes packed, magic={magic_key})")
    return 0


def cmd_selftest():
    xml = (b'<?xml version="1.0" encoding="ASCII"?>\n<MSMElectronicsWorkbench Schema="67">'
           + b"<Item>x</Item>" * 500 + b"</MSMElectronicsWorkbench>\n")
    data = pkware.pack_bytes(xml)
    back = pkware.unpack_bytes(data)
    assert back == xml, "roundtrip mismatch"
    print(f"selftest ok: {len(xml)} bytes xml -> {len(data)} bytes container -> identical")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="show container header and block table")
    p.add_argument("path")

    p = sub.add_parser("unpack", help="extract the XML")
    p.add_argument("path")
    p.add_argument("-o", "--out")

    p = sub.add_parser("pack", help="wrap XML into a container")
    p.add_argument("path")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--magic", choices=sorted(MAGICS), default="ms14")

    sub.add_parser("selftest", help="pack/unpack roundtrip check")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "info":
            return cmd_info(a.path)
        if a.cmd == "unpack":
            return cmd_unpack(a.path, a.out)
        if a.cmd == "pack":
            return cmd_pack(a.path, a.out, a.magic)
        return cmd_selftest()
    except pkware.PkError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
