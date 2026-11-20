# Independent cross-check of the state-change list and the routine rank against public sources not used to
# build them: `sample` fixes the objects to research before any search, `verify` checks every quote against
# the saved page copies, and `score` matches the claims to the list with the cited-event rule.

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import html
import json
import random
import re
import statistics
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

from harness.evals.mode_events import PERIOD, TIMELINE_DAYS, WINDOW_DAYS, _commit, event_date
from harness.evals.state_changes import ACCEPTS
from orbit_watch.sources import data_dir
from orbit_watch.truth import GROUNDTRUTH, read_event_rows

CLAIMS = GROUNDTRUTH / "cross_check.csv"
CLAIM_FIELDS = ["claim_id", "norad_id", "name", "claim_type", "date", "date_end", "date_precision", "lon_from_deg",
                "lon_to_deg", "source_url", "publisher", "quote", "source_kind", "says"]
INDEPENDENT = ("operator", "regulator", "observer", "press")
TLE_DERIVED = "tle_derived"
OUT = Path("findings/cross_check")
RESULT_FIELDS = ["claim_id", "norad_id", "name", "group", "already_cited", "source_kind", "claim_type", "date",
                 "date_end", "date_precision", "status", "event_type", "event_date", "error_days", "nearest_type",
                 "nearest_date", "nearest_offset_days", "events_in_period"]
INDEX_FIELDS = ["file", "url", "fetched_utc", "sha256"]
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
PASSAGE_SPLIT = re.compile(r" \| | \.\.\. ")
RANK = Path("findings/routine/rank.csv")
UNRATED = Path("findings/routine/unrated.csv")
EVENTS = Path("findings/state_changes/events.csv")
SAMPLE = GROUNDTRUTH / "cross_check_sample.csv"
CITED = tuple(GROUNDTRUTH / n for n in ("geo_events.csv", "irregular_objects.csv", "steady_objects.csv"))
SEED = "orbit-watch cross-check 2026-11-20"
TOP_N = 30
DRAWN_N = 20
SAMPLE_FIELDS = ["norad_id", "name", "group", "rank", "already_cited", "sources_found", "searches", "searches_2",
                 "tried"]


def _rows(path: Path) -> list[dict]:
    return read_event_rows(path)[1]


def draw_sample(rank: list[dict], unrated: list[dict], event_norads: set[int], cited: set[int]) -> list[dict]:
    names = {int(r["norad_id"]): r["name"] for r in (*rank, *unrated)}
    ranks = {int(r["norad_id"]): int(r["rank"]) for r in rank}
    top = [int(r["norad_id"]) for r in sorted(rank, key=lambda r: int(r["rank"]))[:TOP_N]]
    pool = sorted(event_norads - set(top))
    drawn = random.Random(SEED).sample(pool, DRAWN_N)
    return [{"norad_id": n, "name": names[n], "group": group, "rank": ranks.get(n, ""),
             "already_cited": int(n in cited)} | dict.fromkeys(SAMPLE_FIELDS[5:], "")
            for group, ns in (("top30", top), ("drawn", drawn)) for n in ns]


def cited_norads(paths=CITED) -> set[int]:
    return {int(r["norad_id"]) for p in paths for r in _rows(p)}


def sample_rows() -> list[dict]:
    return draw_sample(_rows(RANK), _rows(UNRATED), {int(r["norad_id"]) for r in _rows(EVENTS)}, cited_norads())


def write_sample(path: Path = SAMPLE) -> list[dict]:
    rows = sample_rows()
    if path.is_file():
        kept = {int(r["norad_id"]): r for r in _rows(path)}
        for r in rows:
            old = kept.get(r["norad_id"], {})
            r.update({k: old.get(k, "") for k in SAMPLE_FIELDS[5:]})
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SAMPLE_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return rows


def sources_dir() -> Path:
    return data_dir() / "sources" / "cross_check"


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in ("br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        else:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def page_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    if "<" in text[:2000] and re.search(r"<(html|body|div|p|head)\b", text, re.I):
        parser = _Text()
        parser.feed(text)
        text = "".join(parser.parts)
    return html.unescape(text)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[‘’‚‛′`´]", "'", text)
    text = re.sub(r"[“”„‟″]", '"', text)
    text = re.sub(r"[‐-―−]", "-", text)
    text = text.replace("­", "").replace("​", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def passages(quote: str) -> list[str]:
    return [p for p in (normalise(x) for x in PASSAGE_SPLIT.split(quote)) if p]


def read_index(folder: Path) -> dict[str, str]:
    path = folder / "index.csv"
    return {r["url"]: r["file"] for r in _rows(path)} if path.is_file() else {}


def fetch(url: str, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    known = read_index(folder)
    if url in known:
        return folder / known[url]
    req = urllib.request.Request(urllib.parse.quote(url, safe=":/?&=%#+,;~@!$'()*"), headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        kind = resp.headers.get_content_type()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    ext = ".pdf" if kind == "application/pdf" or raw[:5] == b"%PDF-" else ".html"
    name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ext
    (folder / name).write_bytes(raw)
    index = folder / "index.csv"
    new = not index.is_file()
    with open(index, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow({"file": name, "url": url, "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "sha256": hashlib.sha256(raw).hexdigest()})
    return folder / name


def saved_text(path: Path) -> str:
    text_copy = path.with_suffix(".txt")
    return text_copy.read_text(encoding="utf-8") if path.suffix == ".pdf" else page_text(path.read_bytes())


def verify(claims: list[dict], folder: Path) -> list[tuple[str, str]]:
    index, cache, fails = read_index(folder), {}, []
    for c in claims:
        name = index.get(c["source_url"])
        if name is None or not (folder / name).is_file():
            fails.append((c["claim_id"], "no saved copy of the page"))
            continue
        if name not in cache:
            cache[name] = normalise(saved_text(folder / name))
        missing = [p for p in passages(c["quote"]) if p not in cache[name]]
        if missing or not c["quote"].strip():
            fails.append((c["claim_id"], f"not on the saved page: {missing[0] if missing else '(empty quote)'}"))
    return fails


def _first(text: str) -> date:
    parts = [int(x) for x in text.split("-")] + [1, 1]
    return date(parts[0], parts[1], parts[2])


def _last(text: str) -> date:
    n = text.count("-")
    if n == 2:
        return date.fromisoformat(text)
    y, m = (int(text[:4]), int(text[5:7])) if n == 1 else (int(text), 12)
    return (date(y, m, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def period(c: dict) -> tuple[date, date]:
    return _first(c["date"]), _last(c["date_end"] or c["date"])


def offset(c: dict, d: date) -> int:
    if c["date_precision"] in ("day", "month"):
        return (d - event_date(c["date"], c["date_precision"])).days
    lo, hi = period(c)
    return (d - lo).days if d < lo else (d - hi).days if d > hi else 0


def read_events(path: Path = EVENTS) -> list[dict]:
    return [{"norad_id": int(r["norad_id"]), "event_type": r["event_type"], "date": date.fromisoformat(r["date"])}
            for r in _rows(path)]


def _result(c: dict, status: str, **kw) -> dict:
    return {"claim": c, "status": status, **kw}


def _unmatched(c: dict, evs: list[dict]) -> dict:
    def nearest(cands, status):
        j = min(cands, key=lambda j: abs(offset(c, evs[j]["date"])))
        return _result(c, status, nearest=evs[j], nearest_offset=offset(c, evs[j]["date"]))
    near = [j for j, e in enumerate(evs) if abs(offset(c, e["date"])) <= WINDOW_DAYS]
    accepted = [j for j in near if evs[j]["event_type"] in ACCEPTS[c["claim_type"]]]
    if accepted:
        return nearest(accepted, "event_matched_to_another_claim")
    if near:
        return nearest(near, "listed_with_another_type")
    later = [j for j, e in enumerate(evs) if e["event_type"] in ACCEPTS[c["claim_type"]]
             and abs(offset(c, e["date"])) <= TIMELINE_DAYS]
    return nearest(later, "listed_outside_window") if later else _result(c, "not_listed")


def _match_group(cs: list[dict], evs: list[dict]) -> list[dict]:
    pairs = sorted((abs(offset(c, e["date"])), i, j) for i, c in enumerate(cs) for j, e in enumerate(evs)
                   if e["event_type"] in ACCEPTS[c["claim_type"]] and abs(offset(c, e["date"])) <= WINDOW_DAYS)
    used_c, used_e, out = set(), set(), {}
    for _, i, j in pairs:
        if i not in used_c and j not in used_e:
            used_c.add(i)
            used_e.add(j)
            out[i] = _result(cs[i], "matched", event=evs[j], error=offset(cs[i], evs[j]["date"]))
    return [out.get(i) or _unmatched(c, evs) for i, c in enumerate(cs)]


def score_claims(claims: list[dict], events: list[dict]) -> list[dict]:
    by_norad: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        by_norad[e["norad_id"]].append(e)
    results, groups = {}, defaultdict(list)
    for c in claims:
        evs = by_norad.get(int(c["norad_id"]), [])
        if c["claim_type"] in ACCEPTS:
            lo, hi = period(c)
            if hi < PERIOD[0] or lo > PERIOD[1]:
                results[c["claim_id"]] = _result(c, "outside_period")
            else:
                groups[(c["norad_id"], c["source_url"])].append(c)
        elif c["claim_type"] == "stayed":
            lo, hi = period(c)
            inside = [e for e in evs if lo <= e["date"] <= hi]
            results[c["claim_id"]] = _result(c, "stayed_event_listed" if inside else "stayed_no_event_listed",
                                             inside=inside)
        else:
            results[c["claim_id"]] = _result(c, "behaviour")
    for (norad, _), cs in groups.items():
        for r in _match_group(cs, by_norad.get(int(norad), [])):
            results[r["claim"]["claim_id"]] = r
    return [results[c["claim_id"]] for c in claims]


def _block(results: list[dict]) -> dict:
    scored = [r for r in results if r["claim"]["claim_type"] in ACCEPTS and r["status"] != "outside_period"]
    errors = [abs(r["error"]) for r in scored if r["status"] == "matched"]
    return {"claims": len(scored), "matched": len(errors), "objects": len({r["claim"]["norad_id"] for r in scored}),
            "median_abs_error_days": statistics.median(errors) if errors else None,
            "worst_abs_error_days": max(errors) if errors else None,
            "unmatched": dict(Counter(r["status"] for r in scored if r["status"] != "matched"))}


def _split(results: list[dict], key) -> dict:
    out = defaultdict(list)
    for r in results:
        out[key(r)].append(r)
    return {str(k): _block(v) for k, v in sorted(out.items())}


def _brief(r: dict) -> dict:
    c = r["claim"]
    row = {k: c[k] for k in ("claim_id", "norad_id", "name", "claim_type", "date", "date_end", "date_precision",
                             "source_kind", "publisher", "source_url", "quote")}
    row["status"] = r["status"]
    if "nearest" in r:
        row["nearest"] = {"event_type": r["nearest"]["event_type"], "date": r["nearest"]["date"].isoformat(),
                          "offset_days": r["nearest_offset"]}
    if "inside" in r:
        row["events_in_period"] = [f"{e['event_type']} {e['date'].isoformat()}" for e in r["inside"]]
    return row


def search_effort(sample: list[dict]) -> dict:
    rounds = []
    for col in ("searches", "searches_2"):
        n = [int(s[col]) for s in sample if s.get(col, "") != ""]
        if n:
            rounds.append({"objects": len(n), "searches": sum(n), "median_per_object": statistics.median(n),
                           "max_per_object": max(n)})
    return {"searches": sum(r["searches"] for r in rounds), "rounds": rounds}


def summarise(results: list[dict], events: list[dict], sample: list[dict]) -> dict:
    info = {int(s["norad_id"]): s for s in sample}
    for r in results:
        s = info.get(int(r["claim"]["norad_id"]), {})
        r["group"], r["cited"] = s.get("group", ""), str(s.get("already_cited", ""))
    indep = [r for r in results if r["claim"]["source_kind"] in INDEPENDENT]
    tle = [r for r in results if r["claim"]["source_kind"] == TLE_DERIVED]
    dated = lambda rs: {int(r["claim"]["norad_id"]) for r in rs if r["claim"]["claim_type"] in ACCEPTS}
    in_period = [e for e in events if PERIOD[0] <= e["date"] <= PERIOD[1]]
    confirmed = lambda rs, evs: sum(any(r["status"] == "matched" and r["event"] is e for r in rs) for e in evs)
    coverage = {}
    for group in ("top30", "drawn"):
        ns = {n for n, s in info.items() if s["group"] == group}
        evs = [e for e in in_period if e["norad_id"] in ns]
        coverage[group] = {"objects": len(ns), "with_independent_dated_claim": len(ns & dated(indep)),
                           "with_tle_derived_dated_claim_only": len(ns & (dated(tle) - dated(indep))),
                           "without_dated_claim": len(ns - dated(indep) - dated(tle)),
                           "listed_events": len(evs), "events_matched_independent": confirmed(indep, evs),
                           "events_matched_tle_derived": confirmed(tle, evs)}
    top = {n for n, s in info.items() if s["group"] == "top30"}
    starts = [e for e in in_period if e["norad_id"] in top and e["event_type"] == "relocation_start"]
    behaviour = [r for r in results if r["status"] == "behaviour"]
    by_says = defaultdict(set)
    for r in behaviour:
        by_says[r["claim"]["says"]].add(int(r["claim"]["norad_id"]))
    stayed = [r for r in results if r["claim"]["claim_type"] == "stayed"]
    disagree = [r for r in results if r["claim"]["claim_type"] in ACCEPTS
                and r["status"] not in ("matched", "outside_period")] + \
               [r for r in stayed if r["status"] == "stayed_event_listed"]
    return {
        **_commit(), "window_days": WINDOW_DAYS, "near_days": TIMELINE_DAYS,
        "period": [PERIOD[0].isoformat(), PERIOD[1].isoformat()],
        "claims": len(results), "claims_by_type": dict(Counter(r["claim"]["claim_type"] for r in results)),
        "search": search_effort(sample), "coverage": coverage,
        "independent": {"all": _block(indep), "by_group": _split(indep, lambda r: r["group"]),
                        "by_already_cited": _split(indep, lambda r: r["cited"]),
                        "by_source_kind": _split(indep, lambda r: r["claim"]["source_kind"])},
        "tle_derived": {"all": _block(tle), "by_group": _split(tle, lambda r: r["group"]),
                        "by_already_cited": _split(tle, lambda r: r["cited"])},
        "top30_relocation_starts": {"listed": len(starts), "confirmed_independent": confirmed(indep, starts),
                                    "confirmed_tle_derived": confirmed(tle, starts)},
        "behaviour": {"claims": len(behaviour), "objects": len({int(r["claim"]["norad_id"]) for r in behaviour}),
                      "objects_by_says": {k: len(v) for k, v in sorted(by_says.items())}},
        "stayed": [_brief(r) for r in stayed],
        "disagreements": [_brief(r) for r in disagree],
    }


def result_rows(results: list[dict]) -> list[dict]:
    rows = []
    for r in results:
        c = r["claim"]
        row = {k: c[k] for k in ("claim_id", "norad_id", "name", "source_kind", "claim_type", "date", "date_end",
                                 "date_precision")}
        row.update({"group": r.get("group", ""), "already_cited": r.get("cited", ""), "status": r["status"]})
        if "event" in r:
            row.update({"event_type": r["event"]["event_type"], "event_date": r["event"]["date"].isoformat(),
                        "error_days": r["error"]})
        if "nearest" in r:
            row.update({"nearest_type": r["nearest"]["event_type"], "nearest_date": r["nearest"]["date"].isoformat(),
                        "nearest_offset_days": r["nearest_offset"]})
        if "inside" in r:
            row["events_in_period"] = "; ".join(f"{e['event_type']} {e['date'].isoformat()}" for e in r["inside"])
        rows.append(row)
    return rows


def write_score(out: Path = OUT) -> dict:
    events, sample = read_events(), _rows(SAMPLE)
    results = score_claims(_rows(CLAIMS), events)
    summary = summarise(results, events, sample)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                      newline="\n")
    with open(out / "claims.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(result_rows(results))
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cross-check the state-change list and the routine rank against "
                                "independent public sources.")
    cmd = p.add_subparsers(dest="cmd", required=True)
    cmd.add_parser("sample", help=f"write {SAMPLE.name}: the top {TOP_N} of the rank and {DRAWN_N} objects drawn "
                   "with a fixed seed from the other objects on the event list")
    fetch_cmd = cmd.add_parser("fetch", help="save a copy of each page to $ORBIT_WATCH_DATA/sources/cross_check")
    fetch_cmd.add_argument("urls", nargs="+")
    cmd.add_parser("verify", help=f"check every quote in {CLAIMS.name} word for word against its saved page copy")
    cmd.add_parser("score", help=f"match {CLAIMS.name} to {EVENTS} and write {OUT}/summary.json and claims.csv")
    a = p.parse_args(argv)
    if a.cmd == "sample":
        rows = write_sample()
        print(f"wrote {len(rows)} objects to {SAMPLE}")
    elif a.cmd == "fetch":
        for url in a.urls:
            try:
                print(f"{fetch(url, sources_dir()).name} {url}")
            except Exception as e:
                print(f"FAILED {url}: {e}")
    elif a.cmd == "verify":
        claims = _rows(CLAIMS)
        fails = verify(claims, sources_dir())
        for claim_id, why in fails:
            print(f"{claim_id}: {why}")
        print(f"{len(claims) - len(fails)} of {len(claims)} quotes found on their saved pages")
        return 1 if fails else 0
    elif a.cmd == "score":
        s = write_score()
        i, t = s["independent"]["all"], s["tle_derived"]["all"]
        print(f"independent: {i['matched']} of {i['claims']} dated claims matched; "
              f"tle_derived: {t['matched']} of {t['claims']}; {len(s['disagreements'])} disagreements -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
