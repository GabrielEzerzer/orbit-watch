# The published dataset in dataset/: the state-change events and the per-object table joined from the committed
# results with the object catalogue, the data card and the evidence page for the top 30 of the rank, and with
# --charts one longitude chart per evidence object from the element sets.

from __future__ import annotations

import argparse
import csv
import io
import json
import pickle
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from string import Template

from orbit_watch.sources import data_dir
from orbit_watch.truth import read_event_rows

FINDINGS = Path("findings")
OUT = Path("dataset")
EVIDENCE_TOP = 30
EVENT_SOURCE_FIELDS = ["norad_id", "event_type", "date", "signal", "size", "lon_before", "lon_after", "mode_before",
                       "mode_after", "mode_change"]
SCORE_FIELDS = ["scored", "end_of_life", "model", "past_stays", "stay_days", "bits", "off_routine"]
EVENT_FIELDS = (EVENT_SOURCE_FIELDS[:1] + ["name", "owner", "object_type"] + EVENT_SOURCE_FIELDS[1:] + SCORE_FIELDS
                + ["proximity_flag", "near_norad_id"])
CATALOGUE_FIELDS = ["name", "owner", "object_type"]
OBJECT_FIELDS = ["norad_id", *CATALOGUE_FIELDS, "rated", "unrated_reason", "rank", "bits_per_year",
                 "stay_bits_per_year", "rate_bits_per_year", "departures_per_held_year", "held_years",
                 "years_since_first_hold", "state_changes", "relocation_starts", "scored_departures", "end_of_life",
                 "off_routine", "overruns", "proximity_flags", "steps_outside_holds_unchecked"]
RANK_COPY = ["rank", "bits_per_year", "stay_bits_per_year", "rate_bits_per_year", "departures_per_held_year",
             "held_years", "years_since_first_hold"]
TYPES = ["relocation_start", "relocation_end", "graveyard", "keeping_stop", "ns_keeping_stop", "free_burn"]
TARGETS = {"dead": 0.01, "keepers": 0, "cited": 0.9, "planted": 0.9, "stability": 0.5, "as_of": 0.9, "audit": 24,
           "irregular": 0.75, "steady": 0.9}


def rows(path: Path) -> list[dict]:
    return read_event_rows(path)[1]


def key(r: dict) -> tuple[str, str, str]:
    return r["norad_id"], r["event_type"], r["date"]


def catalogue_from_manifest(path: Path) -> dict[int, dict]:
    objects = json.loads(path.read_text(encoding="utf-8"))["objects"]
    out = {}
    for n, o in objects.items():
        s = o.get("satcat") or {}
        out[int(n)] = {"name": s.get("OBJECT_NAME") or "", "owner": s.get("COUNTRY") or "",
                       "object_type": s.get("OBJECT_TYPE") or ""}
    return out


def catalogue_from_objects(path: Path) -> dict[int, dict]:
    return {int(r["norad_id"]): {k: r[k] for k in CATALOGUE_FIELDS} for r in rows(path)}


def build(findings: Path, catalogue: dict[int, dict]) -> tuple[list[dict], list[dict]]:
    routine = findings / "routine"
    events = rows(findings / "state_changes" / "events.csv")
    rank = rows(routine / "rank.csv")
    unrated = rows(routine / "unrated.csv")
    departures = rows(routine / "departures.csv")
    overruns = rows(routine / "overruns.csv")
    flagged = rows(routine / "flagged_arrivals.csv")
    population = [int(r["norad_id"]) for r in rank + unrated]
    if len(population) != len(set(population)):
        raise ValueError("an object is both rated and unrated")
    missing = sorted(set(population) - set(catalogue))
    if missing:
        raise ValueError(f"no catalogue entry for {missing[:10]}; pass --catalogue with the GEO-region manifest")
    for r in rank + unrated:
        if catalogue[int(r["norad_id"])]["name"] != r["name"]:
            raise ValueError(f"{r['norad_id']}: catalogue name differs from the routine results")
    for r in rank:
        if catalogue[int(r["norad_id"])]["owner"] != r["owner"]:
            raise ValueError(f"{r['norad_id']}: catalogue owner differs from rank.csv")
    for r in unrated:
        if catalogue[int(r["norad_id"])]["object_type"] != r["object_type"]:
            raise ValueError(f"{r['norad_id']}: catalogue type differs from unrated.csv")
    dead = {n for n in population if catalogue[n]["object_type"] in ("ROCKET BODY", "DEBRIS")}
    if len(dead) != load_json(routine / "checks_all.json")["dead_objects"]["objects"]:
        raise ValueError("rocket body and debris count differs from checks_all.json")
    if dead & {int(r["norad_id"]) for r in rank}:
        raise ValueError("a rocket body or debris object is rated")

    score = {key(r): r for r in departures}
    flag = {(r["norad_id"], "relocation_end", r["date"]): r for r in flagged}
    if len(score) != len(departures) or len(flag) != len(flagged):
        raise ValueError("duplicate departure or flagged-arrival rows")
    seen = Counter(key(r) for r in events)
    if any(v > 1 for v in seen.values()):
        raise ValueError("duplicate state-change rows")
    lost = [k for k in list(score) + list(flag) if k not in seen]
    if lost:
        raise ValueError(f"score or flag rows with no state change: {lost[:5]}")
    stray = {int(r["norad_id"]) for r in events} - set(population)
    if stray:
        raise ValueError(f"state changes on objects outside the population: {sorted(stray)[:5]}")

    out_events = []
    for r in events:
        n = int(r["norad_id"])
        row = {**r, **catalogue[n]}
        s = score.get(key(r))
        row.update({k: (s[k] if s else "") for k in SCORE_FIELDS})
        if r["event_type"] == "relocation_end":
            f = flag.get(key(r))
            row.update(proximity_flag="1" if f else "0", near_norad_id=f["other_norad_id"] if f else "")
        else:
            row.update(proximity_flag="", near_norad_id="")
        out_events.append({k: row[k] for k in EVENT_FIELDS})
    out_events.sort(key=lambda r: (int(r["norad_id"]), r["date"]))

    counts: dict[int, Counter] = defaultdict(Counter)
    for r in events:
        counts[int(r["norad_id"])]["state_changes"] += 1
        counts[int(r["norad_id"])]["relocation_starts"] += r["event_type"] == "relocation_start"
    for r in departures:
        c = counts[int(r["norad_id"])]
        c["scored_departures"] += r["scored"] == "1"
        c["end_of_life"] += r["end_of_life"] == "1"
        c["off_routine"] += r["off_routine"] == "1"
    for r in overruns:
        counts[int(r["norad_id"])]["overruns"] += 1
    for r in flagged:
        counts[int(r["norad_id"])]["proximity_flags"] += 1

    def counted(n: int) -> dict:
        c = counts[n]
        return {k: c[k] for k in ("state_changes", "relocation_starts", "scored_departures", "end_of_life",
                                  "off_routine", "overruns", "proximity_flags")}

    out_objects = []
    for r in rank:
        n = int(r["norad_id"])
        c = counted(n)
        same = {"departures": "scored_departures", "end_of_life": "end_of_life", "off_routine": "off_routine",
                "overruns": "overruns", "proximity_flags": "proximity_flags"}
        if any(int(r[a]) != c[b] for a, b in same.items()):
            raise ValueError(f"{n}: rank.csv counts differ from the departure, overrun and flag rows")
        out_objects.append({"norad_id": n, **catalogue[n], "rated": 1, "unrated_reason": "",
                            **{k: r[k] for k in RANK_COPY}, **c, "steps_outside_holds_unchecked": ""})
    for r in sorted(unrated, key=lambda r: int(r["norad_id"])):
        n = int(r["norad_id"])
        c = counted(n)
        if int(r["events"]) != c["state_changes"] or int(r["proximity_flags"]) != c["proximity_flags"]:
            raise ValueError(f"{n}: unrated.csv counts differ from the state changes and flag rows")
        out_objects.append({"norad_id": n, **catalogue[n], "rated": 0,
                            "unrated_reason": "never_held" if float(r["held_years"]) == 0 else "held_under_2_years",
                            **{k: "" for k in RANK_COPY}, "held_years": r["held_years"], **c,
                            "steps_outside_holds_unchecked": r["steps_outside_holds_unchecked"]})
    return out_events, out_objects


def csv_text(fields: list[str], table: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(table)
    return buf.getvalue()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def num(x: float) -> str:
    return f"{x:,}" if isinstance(x, int) else f"{x:g}"


def table(head: list[str], body: list[list]) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in body]
    return "\n".join(lines)


def verdict(ok: bool) -> str:
    return "pass" if ok else "**fail**"


def right(v: dict) -> int:
    on = next(x for k, x in v["on_rhythm"].items() if k.startswith("under_"))
    off = next(x for k, x in v["off_rhythm"].items() if k.startswith("at_least_"))
    return on + off


def routine_checks(c: dict, planted: dict, rank: list[dict]) -> tuple[list[list], Counter]:
    tally: Counter = Counter()
    out = []

    def add(name: str, result: str, target: str, v: str) -> None:
        tally[v.strip("*").split(",")[0].split(" ")[0]] += 1
        out.append([name, result, target, v])

    d = c["dead_objects"]
    add("1. Off-routine rows on rocket bodies and debris",
        f"{d['off_routine_rows']} in {num(d['object_years'])} object-years on {d['objects']} objects; "
        f"{d['rated']} rated", f"about {num(TARGETS['dead'])} per object-year",
        verdict(d["per_object_year"] <= TARGETS["dead"] and d["rated"] == 0))
    k = c["logged_keepers"]
    add("2. Off-routine rows on QZS-3, QZS-6 and Fengyun-2H on station",
        f"{k['off_routine_rows']} in {num(k['object_years'])} object-years", str(TARGETS["keepers"]),
        verdict(k["off_routine_rows"] <= TARGETS["keepers"]))
    cd = c["cited_departures"]
    caught = sum(cd[s]["caught"] for s in c["splits"])
    flagged = sum(cd[s]["flagged"] for s in c["splits"])
    held = sum(cd[s]["held_a_year_before"] for s in c["splits"])
    cited = sum(cd[s]["cited_relocation_starts"] for s in c["splits"])
    add("3. Cited relocation starts on objects held a year before them, flagged off-routine when caught",
        f"{flagged} of {caught} caught ({cited} cited, {held} on objects held a year before, {caught} caught)",
        f"{TARGETS['cited']:.0%} of those caught", verdict(caught > 0 and flagged / caught >= TARGETS["cited"]))
    shares = {s: planted[f"{s} 4+1"] for s in planted["splits"]}
    first = {s: planted[f"{s} 3+1"]["both_targets_share"] for s in planted["splits"]}
    add("4. Planted rhythm: 4 moves on a fixed rhythm, then one on or off it; both kinds scored right",
        "; ".join(f"{s} {v['both_targets_share']} of {v['last_move_caught_and_scored']} caught and scored, "
                  f"{right(v) / v['trials']:g} of all {v['trials']}" for s, v in shares.items()) + " (3 moves then 1: " + ", ".join(f"{s} {v}" for s, v in first.items())
        + ")", f"{TARGETS['planted']:.0%} of trials",
        verdict(all(v["both_targets_share"] >= TARGETS["planted"] for v in shares.values())))
    st = c["stability"]
    add("5. Top 30 on 2021 to mid-2023 in the top 60 on the rest",
        f"{st['top_30_first_in_top_60_second']} of {st['of']}; Spearman {round(st['spearman'], 3)}",
        "half", verdict(st["top_30_first_in_top_60_second"] >= TARGETS["stability"] * st["of"]))
    cuts = c["causality"]
    same = {d: v["spearman_vs_full_run_cut_at_same_date"] for d, v in cuts.items()}
    final = {d: v["spearman_vs_full_run_final"] for d, v in cuts.items()}
    for label, side in (("the full run cut at the same date", same), ("the final run", final)):
        passed = [d for d, v in side.items() if v >= TARGETS["as_of"]]
        failed = [d for d in side if d not in passed]
        add(f"6. Spearman of reruns on data cut at each year-end, against {label}",
            ", ".join(f"{d}: {side[d]}" for d in side), num(TARGETS["as_of"]),
            "pass" if not failed else "**fail**" if not passed else
            f"part, pass at {', '.join(passed)}; fail at {', '.join(failed)}")
    a = c["hand_audit"]["top"]
    add("7. Top 30 judged irregular in the blind hand audit", f"{a['class']['irregular']} of {a['objects']}",
        f"{TARGETS['audit']} of {a['objects']}", verdict(a["class"]["irregular"] >= TARGETS["audit"]))
    ir = c["cited_lists"]["irregular"]
    add("8. Cited irregular objects in the top 5%",
        f"{ir['in_top_5_percent']} of {ir['rateable']} rateable ({ir['listed']} listed)",
        f"{TARGETS['irregular']:.0%}", verdict(ir["in_top_5_percent"] >= TARGETS["irregular"] * ir["rateable"]))
    sd = c["cited_lists"]["steady"]
    mid = median(float(r["bits_per_year"]) for r in rank)
    ok = sd["in_lower_half"] >= TARGETS["steady"] * sd["rateable"]
    add("9. Cited steady keepers in the lower half",
        f"{sd['in_lower_half']} of {sd['rateable']}; none of the {sd['listed']} has a scored departure, and "
        f"{sd['rated_share_no_scored_departure']:.1%} of rated objects ({sd['rated_no_scored_departure']} of "
        f"{sd['rated']}) have none (chance {sd['chance_of_at_least_as_many_in_a_random_draw']})",
        f"{TARGETS['steady']:.0%}", verdict(ok) + (f", but weak: the median rated object has {num(mid)} bits per year"
                                                    if ok and mid == 0 else ""))
    return out, tally


def card(findings: Path, events: list[dict], objects: list[dict]) -> str:
    sc = load_json(findings / "state_changes" / "summary.json")
    ev = load_json(findings / "state_changes" / "eval_all.json")
    held_out = load_json(findings / "state_changes" / "false_events_final.json")["false_events"]
    inj = load_json(findings / "state_injection" / "summary.json")
    fresh = load_json(findings / "state_audit_fresh" / "summary.json")
    ro = load_json(findings / "routine" / "summary.json")
    checks = load_json(findings / "routine" / "checks_all.json")
    planted = load_json(findings / "routine" / "planted_all.json")
    rank = rows(findings / "routine" / "rank.csv")
    if len(events) != sc["events"] or len(objects) != sc["objects_processed"]:
        raise ValueError("dataset tables disagree with findings/state_changes/summary.json")

    by_year = sc["events_by_type_and_year"]
    years = sorted({y for t in by_year.values() for y in t})
    counts = table(["type"] + years + ["total"],
                   [[f"`{t}`"] + [by_year[t].get(y, 0) for y in years] + [sc["events_by_type"][t]] for t in TYPES])
    cited = table(["split", "cited events", "found", "median date error (days)", "90th percentile (days)",
                   "same type"],
                  [[s, ev[s]["events"], ev[s]["caught"], num(ev[s]["median_abs_error_days"]),
                    num(round(ev[s]["p90_abs_error_days"], 1)), ev[s]["same_type"]] for s in ("dev", "test")])
    fe = ev["false_events"]
    false_rows = [[", ".join(f"{k} ({v['object_years']})" for k, v in fe["objects"].items()), fe["object_years"],
                   fe["false_events"], "no"],
                  [", ".join(f"{k} ({v['object_years']})" for k, v in held_out["objects"].items()),
                   held_out["object_years"], held_out["false_events"], "yes"]]
    false_tab = table(["satellites (object-years)", "object-years", "false events", "held out"], false_rows)

    def truth(s: str, kind: str, band: str | None, t: str) -> str:
        k = inj[s]["kinds"][kind]
        k = k[band] if band else k
        b = k["by_truth_type"][t]
        return f"{b['caught']}/{b['trials']}, {num(b['median_abs_error_days'])} d"

    plant_rows = []
    for label, kind, band, t in (("relocation, 0.1-3 deg/day, start", "relocation", "normal (0.1-3)", "relocation_start"),
                                 ("relocation, 0.1-3 deg/day, end", "relocation", "normal (0.1-3)", "relocation_end"),
                                 ("relocation, 0.02-0.1 deg/day, start", "relocation", "slow (0.02-0.1)", "relocation_start"),
                                 ("relocation, 0.02-0.1 deg/day, end", "relocation", "slow (0.02-0.1)", "relocation_end"),
                                 ("keeping stop", "keeping_stop", None, "keeping_stop"),
                                 ("graveyard climb", "graveyard", None, "graveyard"),
                                 ("free burn: the stop", "free_burn", None, "keeping_stop"),
                                 ("free burn: the burn", "free_burn", None, "free_burn")):
        plant_rows.append([label] + [truth(s, kind, band, t) for s in inj["splits"]])
    plant_tab = table(["planted change"] + [f"{s}: found, median date error" for s in inj["splits"]], plant_rows)
    vt = fresh["verdicts_by_type"]
    audit_tab = table(["type", "sampled", "real, right type", "artefact", "duplicate", "wrong type"],
                      [[f"`{t}`", sum(vt[t].values()), vt[t].get("real", 0), vt[t].get("artefact", 0),
                        vt[t].get("duplicate", 0), vt[t].get("wrong_type", 0)] for t in TYPES if t in vt])
    ha = checks["hand_audit"]
    cls = ["irregular", "rhythm", "end_of_life", "none", "unclear"]
    routine_audit = table(["group", "objects"] + cls,
                          [[g, ha[g]["objects"]] + [ha[g]["class"].get(k, 0) for k in cls] for g in ("top", "middle")])
    check_rows, tally = routine_checks(checks, planted, rank)
    stay = [r for r in rank if float(r["stay_bits_per_year"]) > 0]
    values = {
        "objects": num(len(objects)), "region_objects": num(sc["geo_dir_object_count"]),
        "holdout": len(sc["skipped_holdout"]), "holdout_ids": ", ".join(map(str, sc["skipped_holdout"])),
        "events": num(len(events)), "objects_with_events": sc["objects_with_events"], "counts_table": counts,
        "rated": ro["rated"], "unrated": num(ro["unrated"]), "never_held": num(ro["unrated_never_held"]),
        "with_bits": ro["rated_with_bits"], "departures": ro["departures"], "scored": ro["departures_scored"],
        "end_of_life": ro["departures_end_of_life_unscored"],
        "commissioning": ro["departures_unscored_commissioning"], "stays_model": ro["scored_by_model"]["stays"],
        "rate_model": ro["scored_by_model"]["rate"], "off_routine": ro["off_routine_departures"],
        "overruns": ro["overruns"], "flagged": ro["flagged_arrivals"], "arrivals": ro["arrivals"],
        "flagged_objects": ro["flagged_objects"], "cited_table": cited, "false_table": false_tab,
        "plant_table": plant_tab, "fresh_table": audit_tab, "fresh_events": fresh["events"],
        "fresh_right": fresh["real_right_type"], "fresh_dated": fresh["real_date_dated"],
        "fresh_median": num(fresh["real_median_abs_error_days"]), "fresh_3": fresh["real_within_3_days"],
        "fresh_max": fresh["real_max_abs_error_days"], "routine_audit_table": routine_audit,
        "checks_table": table(["check", "result", "target", "verdict"], check_rows),
        "checks_n": len(check_rows), "checks_pass": tally["pass"], "checks_fail": tally["fail"],
        "checks_part": tally["part"], "irregular_top": checks["cited_lists"]["irregular"]["in_top_5_percent"],
        "irregular_rateable": checks["cited_lists"]["irregular"]["rateable"],
        "commit_events": sc["commit"][:7], "commit_routine": ro["commit"][:7],
        "commit_cache": ro["belt_cache_commit"][:7], "commit_checks": checks["commit"][:7],
        "commit_planted": planted["commit"][:7], "commit_eval": ev["commit"][:7],
        "commit_injection": inj["commit"][:7], "top": EVIDENCE_TOP,
        "no_catalogue": sum(not o["name"] for o in objects),
        "stay_objects": len(stay), "stay_ranks": ", ".join(r["rank"] for r in stay),
        "empty_lon": sum(not e["lon_before"] or not e["lon_after"] for e in events),
    }
    return CARD.substitute(values)


def audit_notes(findings: Path) -> dict[int, dict]:
    routine = findings / "routine"
    key = {r["audit_id"]: r for r in rows(routine / "audit_key.csv")}
    out = {}
    for v in rows(routine / "audit_verdicts.csv"):
        out[int(key[v["audit_id"]]["rank"])] = {**v, "group": key[v["audit_id"]]["group"]}
    return out


def evidence(findings: Path, events: list[dict], objects: list[dict]) -> str:
    notes = audit_notes(findings)
    top = [o for o in objects if o["rated"] == 1][:EVIDENCE_TOP]
    by_obj = defaultdict(list)
    for e in events:
        by_obj[int(e["norad_id"])].append(e)
    irregular = sum(notes[int(o["rank"])]["class"] == "irregular" for o in top)
    lines = ["# Evidence: the top 30 of the irregularity rank", "",
             f"One section per object, in rank order: its standing from [`../objects.csv`](../objects.csv), its state "
             f"changes from [`../events.csv`](../events.csv), the class a blind judge gave it from its chart "
             f"(`findings/routine/audit_verdicts.csv`, joined to the rank through `audit_key.csv`) and a chart of its "
             f"mean longitude. The judge saw an earlier four-panel chart with no ranks or scores. "
             f"{irregular} of these {len(top)} were judged irregular; the others are marked below.", "",
             "In each chart the green bands are the held spans the score uses and each vertical line is one state "
             "change, numbered as in the table under it. A number on a red badge is an off-routine departure "
             "(5 bits or more). The longitude axis covers the object's holds and listed longitudes, and runs on "
             "across 180 deg for an object whose longitudes cross it, with its labels wrapped back to -180 to 180. "
             "Element sets outside the axis, such as launch and transfer orbits or the drift after a graveyard "
             "climb, are counted at the top right and not drawn.", ""]
    if any(notes[int(o["rank"])]["class"] == "unclear" for o in top):
        lines += ["For an `unclear` object a `departures_real` of `no` means the judge could not see the move on the "
                  "four-panel chart, whose axes its launch points stretched, not that the move was disproved. The "
                  "charts here zoom to the object's own longitudes.", ""]
    lines += [f"- [{o['rank']}. {o['name']} ({o['norad_id']})](#{anchor(o)})" for o in top]
    for o in top:
        n = int(o["norad_id"])
        v = notes[int(o["rank"])]
        if int(v["norad_id"]) != n:
            raise ValueError(f"audit row for rank {o['rank']} names {v['norad_id']}, not {n}")
        lines += ["", f"## {heading(o)}", "",
                  f"Owner `{o['owner']}`, {o['object_type'].lower()}. Held {o['held_years']} years. "
                  f"{o['bits_per_year']} bits per year: {o['stay_bits_per_year']} from the stay model and "
                  f"{o['rate_bits_per_year']} from the rate model. Scored departures {o['scored_departures']} "
                  f"(off-routine {o['off_routine']}), end of life {o['end_of_life']}, stay overruns "
                  f"{o['overruns']}, proximity flags {o['proximity_flags']}.", ""]
        if v["class"] != "irregular":
            lines += [f"**Not judged irregular by the blind audit: `{v['class']}`.**", ""]
        lines += [f"Blind audit: `{v['class']}`; listed departures real: `{v['departures_real']}`. "
                  f"Judge's note: {v['evidence']}", "",
                  f"![Mean longitude of {o['name']} ({n}), 2021-2025, with holds and state changes]({n}.png)", "",
                  table(["#", "date", "type", "lon before (deg E)", "lon after (deg E)", "bits", "off-routine",
                         "proximity flag"],
                        [[k, e["date"], f"`{e['event_type']}`", e["lon_before"], e["lon_after"], e["bits"],
                          {"1": "yes", "0": ""}.get(e["off_routine"], ""),
                          f"yes, near {e['near_norad_id']}" if e["proximity_flag"] == "1" else ""]
                         for k, e in enumerate(by_obj[n], 1)])]
    return "\n".join(lines) + "\n"


def heading(o: dict) -> str:
    return f"{o['rank']}. {o['name']} ({o['norad_id']})"


def anchor(o: dict) -> str:
    keep = "".join(ch for ch in heading(o).lower() if ch.isalnum() or ch in " -_")
    return keep.replace(" ", "-")


def charts(out: Path, events: list[dict], objects: list[dict], geo_dir: Path, cache: Path) -> int:
    from orbit_watch.charts import chart
    from orbit_watch.elements import parse_tle
    from orbit_watch.series import distinct_epochs

    holds = {o["norad"]: o["holds"] for o in pickle.loads(cache.read_bytes())["objects"]}
    by_obj = defaultdict(list)
    for e in events:
        by_obj[int(e["norad_id"])].append(e)
    top = [o for o in objects if o["rated"] == 1][:EVIDENCE_TOP]
    for o in top:
        n = int(o["norad_id"])
        (records,) = distinct_epochs(parse_tle((geo_dir / f"{n}.tle").read_text(encoding="utf-8"))).values()
        chart(out / "evidence" / f"{n}.png", f"{o['rank']}. {o['name']} ({n})", records, by_obj[n], holds[n],
              panels=("lon",), numbered=True, size=(10, 4.2), dpi=90)
        print(f"chart {n} {o['name']}", flush=True)
    return len(top)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write dataset/: the state-change events and per-object table joined "
                                "from the committed results, the data card, the evidence page for the top 30 of the "
                                "rank, and with --charts one chart per evidence object.")
    p.add_argument("--out", type=Path, default=OUT, help="folder to write (default %(default)s)")
    p.add_argument("--catalogue", type=Path, help="GEO-region manifest.json to take names, owners and types from; "
                   "by default they are kept from OUT/objects.csv")
    p.add_argument("--charts", action="store_true", help="also draw the evidence charts from the element sets")
    p.add_argument("--geo-dir", type=Path, help="for --charts: folder of <norad>.tle files; default $ORBIT_WATCH_DATA/geo")
    p.add_argument("--cache", type=Path, help="for --charts: belt cache; default $ORBIT_WATCH_DATA/routine/belt.pkl")
    a = p.parse_args(argv)
    if not a.catalogue and not (a.out / "objects.csv").exists():
        p.error(f"{a.out / 'objects.csv'} does not exist; pass --catalogue with the GEO-region manifest.json")
    cat =catalogue_from_manifest(a.catalogue) if a.catalogue else catalogue_from_objects(a.out / "objects.csv")
    events, objects = build(FINDINGS, cat)
    write(a.out / "events.csv", csv_text(EVENT_FIELDS, events))
    write(a.out / "objects.csv", csv_text(OBJECT_FIELDS, objects))
    write(a.out / "README.md", card(FINDINGS, events, objects))
    write(a.out / "evidence" / "README.md", evidence(FINDINGS, events, objects))
    print(f"{a.out}: {len(events)} events, {len(objects)} objects")
    if a.charts:
        n = charts(a.out, events, objects, a.geo_dir or data_dir() / "geo",
                   a.cache or data_dir() / "routine" / "belt.pkl")
        print(f"{n} charts in {a.out / 'evidence'}")
    return 0


CARD = Template("""# GEO station-keeping state changes and irregularity rank, 2021-2025

Dated changes in how every object in the geostationary belt was flown from 2021 to 2025, and a rank of
the objects whose relocations break their own routine, built only from public orbital elements.
Written by `python -m orbit_watch.jobs.dataset` from the committed results in `findings/`; do not edit
by hand.

| File | What it holds |
|---|---|
| [`events.csv`](events.csv) | $events state changes on $objects_with_events objects, one row each, with the object's name, owner and type and, for departures, the routine score |
| [`objects.csv`](objects.csv) | the $objects objects in the population, one row each: rated or not and why, rank, bits per year and counts |
| [`evidence/`](evidence/README.md) | the top $top of the rank: each object's state changes, a longitude chart and the blind hand audit's verdict |

## What it covers

- **Period.** Element sets with epochs from 2021-01-01 to 2025-12-31. Dates are UTC calendar days.
- **Population.** The $region_objects objects with any element set in ESA's GEO region (mean motion
  0.9-1.1 rev/day, eccentricity at most 0.2, inclination at most 70 deg) in that period, less the
  $holdout objects held out to score the method ($holdout_ids): **$objects objects**, payloads,
  rocket bodies and debris alike. $rated are rated (held at least 2 years in total) and $unrated are
  not; $never_held of those were never held.
- **State change.** One change of an object's station-keeping state, dated to the day from the element
  sets. Each 30-day window is first labelled with ESA's mode classes (held in longitude, drifting,
  librating and so on); where the mode changes, the day is found from the drift rate, the longitude
  box or the burns in the semi-major axis.

| `event_type` | What happened |
|---|---|
| `relocation_start` | a held object left its slot and was held again later, was still moving at relocation speed when the data end, or moved at relocation speed until a graveyard climb |
| `relocation_end` | a moving object started to hold a slot |
| `graveyard` | a held object left and its semi-major axis rose at least 150 km, with no later hold; or an object never held climbed at least 150 km above its first 90 days and stayed there |
| `keeping_stop` | a held object stopped east-west station keeping with no climb, no later hold and no move under way at the end of the data, or drifted slowly for more than 90 days before a climb |
| `ns_keeping_stop` | a held object stopped correcting its inclination but kept its longitude |
| `free_burn` | a step of at least 1 km in the semi-major axis by an object never held again |

Rows per type and year (`findings/state_changes/summary.json`):

$counts_table

Arrivals outnumber starts because many objects' first relocation event is an arrival: objects launched
in the period or already moving in January 2021.

**Departures and the rank.** A *departure* is a `relocation_start`, `graveyard` or `keeping_stop` row
($departures in all). Each `relocation_start` is scored by how surprising it is against the object's own
record before it, in bits (`-log2 p`): with 3 or more past stays (arrival to next departure), by
where the stay falls under a log-normal fitted to those stays (the *stay* model); otherwise by the
object's own departure rate shrunk towards the belt's (the *rate* model, which ignores timing). A
departure of 5 bits or more is *off-routine*. Graveyard moves and keeping stops are end of life:
listed, never scored. Relocation starts in the first 180 days after an object's first element set are
listed and not scored. Of the $departures departures, $scored are scored ($stays_model by the stay
model, $rate_model by the rate model), $end_of_life are end of life and $commissioning are early starts;
$off_routine are off-routine. There are $overruns stay overruns, and $flagged of the $arrivals arrivals,
on $flagged_objects objects, carry a proximity flag. Objects held at least 2 years are ranked by bits
per year; only $with_bits of the $rated rated objects have any bits. The 2-year bar is part of
the method, so recently launched inspectors and rarely held objects are on the unrated list, not in
the rank. The full method is in
[orbit_watch/README.md](../orbit_watch/README.md#routine-score-and-irregularity-rank).

## Columns of `events.csv`

Rows are sorted by `norad_id`, then `date`. An empty cell means the column does not apply to that row
unless the column says otherwise.

| Column | Meaning |
|---|---|
| `norad_id` | NORAD catalogue number |
| `name` | SATCAT object name; empty for the $no_catalogue objects with no SATCAT entry |
| `owner` | SATCAT owner code (`COUNTRY`): a country or organisation, such as `US`, `PRC`, `CIS`, `ITSO`, `SES` or `EUTE`; every US operator is `US`; empty with no SATCAT entry |
| `object_type` | SATCAT type: `PAYLOAD`, `ROCKET BODY` or `DEBRIS`; empty with no SATCAT entry |
| `event_type` | one of the six types above |
| `date` | the UTC day of the change. A departure is the first element set that leaves the hold's drift band or longitude box and stays out 5 days, or the last burn plus half the burn interval; an arrival the first set that stays inside the new slot's band; a change inside a gap of more than 2 days is placed in the gap from the first set after it |
| `signal` | what dated the change: `rate_exit` or `rate_entry` (drift rate or longitude leaving or entering the hold), `burn_gap` (last east-west burn plus half the burn interval), `a_step` (a step in the semi-major axis), `ns_gap` (last inclination correction plus half the median interval between corrections), `mode_change` (no sustained exit or entry within 45 days, so the 30-day mode boundary is used) |
| `size` | per type: `relocation_start` km, the median semi-major axis of the first moving run minus the hold's, negative when the object drifts east (0 when the next window is already held); `relocation_end` 0; `graveyard` and `keeping_stop` km, the highest semi-major axis after the hold minus the hold's median (0 for a keeping stop followed by a move or climb); `ns_keeping_stop` deg, the largest inclination after it; `free_burn` m, the step detector's step, which can have the opposite sign to the net change on a steady climb |
| `lon_before`, `lon_after` | mean longitude before and after the change, deg east from -180 to 180 (west is negative): from or into a hold, the centre of the hold's longitude range (of its 30 days next to the change when the range is wider than 0.5 deg); on an arrival from a stretch that is not held, `lon_before` is the median of the 10 days before it; for a departure with no later hold, `lon_after` is the median of the last 10 days of the data. Empty when those 10 days hold no element set ($empty_lon rows) |
| `mode_before`, `mode_after` | ESA mode class of the 30-day mode segments either side: `controlled_lon_inc` (held, inclination controlled), `controlled_lon` (held), `drifting`, `librating_75E`, `librating_105W`, `librating_both`, `out_of_region` |
| `mode_change` | the date of the 30-day mode boundary the change came from |
| `scored` | departures only: 1 if the relocation start is scored; 0 for end-of-life rows and for starts in an object's first 180 days |
| `end_of_life` | departures only: 1 for `graveyard` and `keeping_stop`, else 0 |
| `model` | `stays` or `rate` for a relocation start; empty for end-of-life rows |
| `past_stays` | departures only: measured stays in the object's record before it |
| `stay_days` | departures only: days since the arrival that opened the stay; empty when the hold started without an arrival row |
| `bits` | relocation starts only: `-log2 p`, with `p` floored at 1e-4 (13.3 bits). Also shown for unscored early starts, where it does not count toward the rank; empty when no belt rate existed yet |
| `off_routine` | departures only: 1 if scored at 5 bits or more, else 0 |
| `proximity_flag` | `relocation_end` rows only: 1 when, over the 10 days from the arrival, another object with a different owner code and launch was already there, within 0.1 deg in longitude and 10 km in semi-major axis; else 0 |
| `near_norad_id` | the neighbour that raised the proximity flag |

## Columns of `objects.csv`

Rated objects come first in rank order, then the unrated ones by `norad_id`. An empty cell means the
column does not apply to that object.

| Column | Meaning |
|---|---|
| `norad_id`, `name`, `owner`, `object_type` | as in `events.csv` |
| `rated` | 1 if held at least 2 years in total, else 0 |
| `unrated_reason` | unrated only: `never_held` (no held span in the data) or `held_under_2_years` |
| `rank` | rated only: 1 is the most irregular; ties are broken by departures per held year, then `norad_id` |
| `bits_per_year` | rated only: the sum of the bits of the object's scored departures over `years_since_first_hold` |
| `stay_bits_per_year`, `rate_bits_per_year` | rated only: the same, split by the model that scored each departure |
| `departures_per_held_year` | rated only: `scored_departures` over `held_years` |
| `held_years` | years held in longitude, summed over held spans |
| `years_since_first_hold` | rated only: years from the start of the first hold to the last element set; a hold under way in January 2021 starts at the first element set |
| `state_changes` | rows in `events.csv` |
| `relocation_starts` | `relocation_start` rows, scored or not |
| `scored_departures` | scored relocation starts |
| `end_of_life` | `graveyard` and `keeping_stop` rows |
| `off_routine` | off-routine departures |
| `overruns` | stays that lasted past the 99th percentile of the object's own fitted stays (needs 3 past stays); dated in `findings/routine/overruns.csv`, not part of the rank |
| `proximity_flags` | flagged arrivals |
| `steps_outside_holds_unchecked` | unrated only: steps the burn detector finds outside holds. They are unchecked: outside holds the detector also fires on dead objects |

## How good it is

Every number below is read from the file named with it.

### The state-change list

**Cited events.** Real relocations, graveyard moves and ends of keeping with a public source
(`groundtruth/geo_events.csv`), split by a hash into dev (used to build the rules) and test (never used
to choose a rule). An event counts as found when a change lies within 45 days of it
(`findings/state_changes/eval_all.json`):

$cited_table

**False events on logged keepers.** Satellites with published burn logs, while the logs show them on
station; every departure, arrival or stop listed there is false. The target is at most 0.2 per
object-year (`eval_all.json` and `false_events_final.json` in `findings/state_changes/`):

$false_table

**Planted changes.** Relocations, keeping stops, graveyard climbs and free burns planted in the real
element sets of held satellites (`findings/state_injection/summary.json`):

$plant_table

**Hand audit.** $fresh_events events drawn from a frozen copy of the list, leaving out every object in an
earlier audit, and judged from charts of their element sets (`findings/state_audit_fresh/summary.json`):
$fresh_right are real with the right type; of the $fresh_dated that could be dated, the median error is
$fresh_median days, $fresh_3 are within 3 days and the largest is $fresh_max days. Six sampled rows
changed in the final list after the verdicts, each toward the hand reading, and were not judged again.
An earlier audit (`findings/state_audit/`) is in-sample, since rules were written after it, and is not
counted here.

$fresh_table

### The routine score and rank

**Of the $checks_n rows below (check 6 has one row per run it is compared with), $checks_pass pass,
$checks_fail fail and $checks_part passes only in part.** Every target was set before the first run,
with one exception: the stay window's share was chosen on check 4's dev trials, so check 4's test
trials are its held-out result. The rank agrees with a blind reading of its top 30 charts and keeps
cited steady keepers out of its upper half, but it flags few cited relocations as off-routine, only
$irregular_top of the $irregular_rateable cited irregular objects held long enough to rate are in its
top 5%, it is not stable between the two halves of the period, a rank on part of the data does not
predict the five-year rank, and the planted rhythm test is below its target. Only $stay_objects rated
objects get any bits from the stay model (ranks $stay_ranks); everywhere else the order is set by the
rate model alone, which counts how often and how late an object left, not whether it left on its own
schedule. Sources: `checks_all.json` and `planted_all.json` in `findings/routine/`.

$checks_table

**Blind audit (check 7).** The top 30 and 20 objects from the middle of the rank were shuffled, and a
judge who saw only one chart per object (longitude, drift rate, semi-major axis and inclination with
holds and changes marked, no ranks or scores) gave each a class (`audit_verdicts.csv` and
`audit_key.csv` in `findings/routine/`):

$routine_audit_table

The [evidence page](evidence/README.md) shows each top-30 object with its class and the judge's note.

## Known limits

Each is an open issue labelled `debt`.

- Slow relocations, 0.02-0.05 deg/day, are missed more often and dated later ([#78](../../../issues/78)).
- Keeping stops near the stable longitudes 75 deg E and 105 deg W are dated late or missed, because a
  free object there barely drifts ([#79](../../../issues/79)).
- A change inside a long gap in the element sets is dated at the edge of the gap ([#70](../../../issues/70)).
- A slow keeping stop more than one burn interval before a move gives two departures for one move
  ([#81](../../../issues/81)).
- Rows known to be off: 36411's relocation start is dated months before its real departure in April
  2023 ([#96](../../../issues/96)); 43874's late-2022 start is dated 15 days early, at a hop inside its
  slot ([#94](../../../issues/94)); SJ-17 (41838) is listed as a relocation start in November 2025 that may
  be an unfinished graveyard climb ([#68](../../../issues/68)).
- A keeping stop dated from a natural exit has no upper limit on the gap after the last burn
  ([#97](../../../issues/97)); three event rules have synthetic failure cases not seen in the belt list
  ([#84](../../../issues/84)).
- The mode layer works in 30-day windows, and near the stable points a hold can be misread as control or
  left undetermined ([#32](../../../issues/32), [#30](../../../issues/30), [#29](../../../issues/29)).
- Most departures are scored by the rate model, so below the top few the rank counts departures rather
  than judging their timing ([#87](../../../issues/87)).
- The planted rhythm test stays under its target ([#88](../../../issues/88)).
- Check 9 is weak while the median rated object has 0 bits per year ([#90](../../../issues/90)).
- The proximity flag's owner code is per country, so an arrival next to another operator of the same
  country is never flagged ([#89](../../../issues/89)).

All open limits: [issues labelled `debt`](../../../issues?q=is%3Aissue+is%3Aopen+label%3Adebt).

## Provenance and licence

- Element sets: the yearly full-catalogue TLE bundles of the CC0 Kaggle dataset
  [historical-tle-datasets](https://www.kaggle.com/datasets/vaibhavpandey12382/historical-tle-datasets).
  The raw element sets are not redistributed here.
- Object names, owners and types: the [Space-Track](https://www.space-track.org) SATCAT.
- Mode classes: ESA Space Debris Office, *Classification of Geosynchronous Objects*, Issue 21.0 (2019).
- Cited events and burn logs used for scoring: [groundtruth/README.md](../groundtruth/README.md).
- The list was written at commit `$commit_events` and scored against the cited events at
  `$commit_eval` and the planted changes at `$commit_injection`; the rank at `$commit_routine` from a
  belt cache built at `$commit_cache`, and its checks at `$commit_checks` and `$commit_planted`. Each
  result file records the commit that wrote it.
- Licence: MIT, as the repository; see [LICENSE](../LICENSE).

## Regenerate

From the repository root, with the package installed (`pip install -e .`):

```
python -m orbit_watch.jobs.dataset
```

This rewrites the two tables, this card and the evidence page from `findings/` and needs no data or
network; names, owners and types are kept from `objects.csv`. `--catalogue PATH` takes them from a
GEO-region `manifest.json` with SATCAT entries instead, and `--charts` redraws the evidence charts,
which need the element sets and the belt cache under `$$ORBIT_WATCH_DATA` (see
[docs/features.md](../docs/features.md)). `tests/test_dataset.py` fails when a table, this card or the
evidence page no longer matches what the job writes.

## Cite

Cite the orbit-watch repository and the commit you used (`git rev-parse HEAD`), and name the files.
""")


if __name__ == "__main__":
    raise SystemExit(main())
