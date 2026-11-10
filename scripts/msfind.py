#!/usr/bin/env python3
"""Multisim component library lookup: Chinese name / English name / part number
-> database path `主数据库 > Group > Family > Component`.

    python msfind.py 电阻              # keyword: what family to pick, with notes
    python msfind.py LM358             # part number / free search
    python msfind.py 555 --json        # machine readable
    python msfind.py --list            # the 106 curated keywords
    python msfind.py --groups          # 20 groups with counts
    python msfind.py 电容 --limit 0    # everything

Data:  ../data/mslook_data.json.gz  (35,303 components + curated keywords)
       ../data/cn_aliases.json      (105 Chinese -> family/term mappings)
Both were read out of the local Multisim 14.0 Jet database (read-only copy);
nothing here touches the installed library.
"""
import argparse
import difflib
import gzip
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
DB_CN = {"master": "主数据库", "corporate": "企业数据库", "user": "用户数据库"}
COLS = ("db", "group", "family", "component", "function", "manufacturer",
        "pkg_type", "package", "pins")

_cache = {}


def load():
    if "data" in _cache:
        return _cache["data"]
    path = os.path.join(DATA, "mslook_data.json.gz")
    if not os.path.exists(path):
        raise SystemExit(f"missing data pack: {path}\n把 mslook_data.json.gz 放进 {os.path.normpath(DATA)}/")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    rows = [dict(zip(COLS, r)) for r in payload.get("rows", [])]
    kws = payload.get("keywords", {})
    aliases = {}
    apath = os.path.join(DATA, "cn_aliases.json")
    if os.path.exists(apath):
        with open(apath, encoding="utf-8") as f:
            aliases = json.load(f)
    _cache["data"] = (rows, kws, aliases)
    return _cache["data"]


def fmt_path(r):
    return "%s > %s > %s > %s" % (DB_CN.get(r["db"], r["db"]), r["group"], r["family"], r["component"])


# ---- keyword mode: curated intent -> concrete families, with the caveats ----------

def resolve_keyword(term, kws):
    t = term.strip().lower()
    for k, v in kws.items():
        if t == k.lower() or t in [s.lower() for s in v.get("synonyms", [])]:
            return k, v
    for k, v in kws.items():
        if len(t) >= 2 and (t in k.lower() or k.lower() in t):
            return k, v
    return None, None


def rule_hit(rule, row):
    if rule.get("family") and row["family"] != rule["family"]:
        return False
    if rule.get("group") and row["group"] != rule["group"]:
        return False
    hay = (row["component"] + " " + row["function"]).lower()
    return all(term.lower() in hay for term in rule.get("terms", []))


def keyword_hits(entry, rows):
    seen, out = set(), []
    for rule in entry.get("rules", []):
        tag = rule.get("tag", "")
        hits = [r for r in rows if rule_hit(rule, r)]
        for row in sorted(hits, key=lambda r: r["component"].lower()):
            key = (row["db"], row["family"], row["component"])
            if key in seen:
                continue
            seen.add(key)
            out.append((tag, row))
    return out


# ---- free search: part number, English, or Chinese via aliases --------------------

def translate(query, aliases):
    q = query.lower()
    families, groups, terms = set(), set(), []
    for key in sorted(aliases, key=len, reverse=True):
        if key.lower() in q:
            entry = aliases[key]
            families.update(entry.get("families", []))
            groups.update(entry.get("groups", []))
            terms.extend(entry.get("terms", []))
            q = q.replace(key.lower(), " ")
    return " ".join(q.split()), families, groups, terms


def score(row, q, families, groups, terms):
    name = row["component"].lower()
    func = row["function"].lower()
    s = 0
    if q:
        if name == q:
            s = 1000
        elif name.startswith(q):
            s = 700
        elif q in name:
            s = 500
        elif q in func:
            s = 320
        elif q in row["family"].lower():
            s = 240
        elif q in row["group"].lower():
            s = 160
    if families:
        if row["family"] in families:
            s += 260
        elif s == 0:
            return 0
    if groups:
        if row["group"] in groups:
            s += 140
        elif s == 0 and not families:
            return 0
    for t in terms:
        t = t.lower()
        if t in name:
            s += 60
        elif t in func:
            s += 25
    return s if (q or families or groups) else 0


def search(query, rows, aliases, group=None, family=None, limit=20, fuzzy=False):
    if group:
        rows = [r for r in rows if r["group"].lower() == group.lower()]
    if family:
        rows = [r for r in rows if r["family"].lower() == family.lower()]
    q, fams, grps, terms = translate(query, aliases)
    if fams:
        fams = {f.upper() for f in fams}
    scored = [(score(r, q, fams, grps, terms), r) for r in rows]
    scored = [(s, r) for s, r in scored if s > 0]
    if fuzzy and q and len(q) >= 3:
        names = {r["component"].lower() for r in rows}
        close = set(difflib.get_close_matches(q, list(names), n=limit, cutoff=0.72))
        for r in rows:
            if r["component"].lower() in close and score(r, q, fams, grps, terms) == 0:
                scored.append((150, r))
    scored.sort(key=lambda x: (-x[0], x[1]["family"], x[1]["component"].lower()))
    seen, out = set(), []
    for s, r in scored:
        key = (r["db"], r["family"], r["component"])
        if key in seen:
            continue
        seen.add(key)
        out.append((s, r))
        if limit and len(out) >= limit:
            break
    return out


# ---- cli -------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Multisim component library lookup")
    ap.add_argument("query", nargs="*", help="中文名 / 英文名 / 型号，如 电阻 / LM358 / 555")
    ap.add_argument("--limit", type=int, default=10, help="0 = all")
    ap.add_argument("--group", help="limit to a group, e.g. Basic / Analog / TTL")
    ap.add_argument("--family", help="limit to a family, e.g. CAPACITOR / OPAMP")
    ap.add_argument("--fuzzy", action="store_true", help="fuzzy match when nothing is found")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", action="store_true", help="list the curated keywords")
    ap.add_argument("--groups", action="store_true", help="list groups with counts")
    a = ap.parse_args(argv)

    rows, kws, aliases = load()

    if a.list:
        for k, v in kws.items():
            kind = "仪表" if v.get("instrument") and not v.get("rules") else "元件"
            print("%-10s %-26s %s" % (k, v.get("en", ""), kind))
        return 0
    if a.groups:
        counts = {}
        for r in rows:
            counts[r["group"]] = counts.get(r["group"], 0) + 1
        for g, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print("%-26s %6d" % (g, n))
        return 0

    query = " ".join(a.query).strip()
    if not query:
        ap.print_help()
        return 1

    key, entry = resolve_keyword(query, kws)
    if entry is not None:
        hits = keyword_hits(entry, rows)
        items = [{"tag": tag, "path": fmt_path(r), "family": r["family"], "group": r["group"],
                  "component": r["component"], "function": r["function"],
                  "manufacturer": r["manufacturer"],
                  "package": r["package"] or r["pkg_type"], "pins": r["pins"]}
                 for tag, r in hits]
        if a.json:
            print(json.dumps({"keyword": query, "english": entry.get("en", ""),
                              "instrument": entry.get("instrument", ""),
                              "note": entry.get("note", ""), "items": items},
                             ensure_ascii=False, indent=1))
            return 0
        print("【%s】%s" % (query, entry.get("en", "")))
        if entry.get("instrument"):
            print("    " + entry["instrument"])
        if not items and not entry.get("instrument"):
            print("    没有命中，试试 --fuzzy 或直接搜型号")
        if items:
            fams = {}
            for it in items:
                k = "%s/%s" % (it["group"], it["family"])
                fams[k] = fams.get(k, 0) + 1
            top = sorted(fams.items(), key=lambda kv: -kv[1])[:8]
            print("    命中系列: " + ", ".join("%s(%d)" % (k, n) for k, n in top))
        show = items if not a.limit else items[:a.limit]
        for i, it in enumerate(show, 1):
            print("  %2d. %s%s" % (i, it["path"], ("  [%s]" % it["tag"]) if it["tag"] else ""))
        if a.limit and len(items) > a.limit:
            print("      ... 共 %d 条，--limit 0 看全部" % len(items))
        if entry.get("note"):
            print("    说明: " + entry["note"])
        return 0

    hits = search(query, rows, aliases, group=a.group, family=a.family,
                  limit=a.limit or 9999, fuzzy=a.fuzzy)
    if not hits:
        print("未找到：%s（试试 --fuzzy、换英文关键词，或 --list 看已收录的中文词）" % query)
        return 2
    if a.json:
        print(json.dumps([dict(score=s, path=fmt_path(r), **r) for s, r in hits],
                         ensure_ascii=False, indent=1))
        return 0
    for i, (s, r) in enumerate(hits, 1):
        print("[%02d] %s" % (i, fmt_path(r)))
        if r["function"]:
            print("     功能: " + r["function"][:90])
        if r["manufacturer"]:
            print("     厂商: " + r["manufacturer"])
        pkg = r["package"] or r["pkg_type"]
        if pkg:
            print("     封装: " + pkg + (("（%s 脚）" % r["pins"]) if r["pins"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
