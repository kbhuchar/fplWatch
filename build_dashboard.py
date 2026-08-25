"""
Reads fpl_data.json (produced by fetch_fpl.py) and computes the curated
stats the dashboard needs: within-league squad overlap, most-owned players,
captain picks, transfer/chip summary, and (once YouTuber IDs are added to
fetch_fpl.py) league-vs-YouTuber comparisons.

Writes dashboard_data.json for inspection and prints a JS-ready JSON blob
you can paste into dashboard.html's DATA constant.
"""
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

YOUTUBER_LABELS = ["FPL Harry", "Let's Talk FPL", "FPL Focal", "FPL Raptor"]


def latest_gw_data(manager, current_gw):
    picks = manager["picks_by_gw"].get(str(current_gw)) or manager["picks_by_gw"].get(current_gw)
    stats = manager["gw_stats"].get(str(current_gw)) or manager["gw_stats"].get(current_gw)
    return picks, stats


def build_within_league_overlap(league_managers, current_gw):
    names = [m["label"] for m in league_managers]
    squads = []
    for m in league_managers:
        picks, _ = latest_gw_data(m, current_gw)
        squads.append(picks["squad"] if picks else [])
    matrix = []
    shared = []
    for i in range(len(league_managers)):
        row, srow = [], []
        for j in range(len(league_managers)):
            if i == j:
                row.append(1.0)
                srow.append(len(squads[i]))
            else:
                a, b = set(squads[i]), set(squads[j])
                size = len(squads[i]) or len(squads[j])
                ov = (len(a & b) / size) if size else None
                row.append(round(ov, 3) if ov is not None else None)
                srow.append(len(a & b))
        matrix.append(row)
        shared.append(srow)
    return {"managers": names, "matrix": matrix, "shared": shared}


def build_most_owned(league_managers, players, current_gw):
    counts = {}
    owners = {}
    for m in league_managers:
        picks, _ = latest_gw_data(m, current_gw)
        if not picks:
            continue
        for pid in picks["squad"]:
            counts[pid] = counts.get(pid, 0) + 1
            owners.setdefault(pid, []).append(m["label"])
    rows = []
    for pid, count in counts.items():
        p = players.get(str(pid)) or players.get(pid)
        if not p:
            continue
        rows.append({
            "name": p["name"],
            "team": p["team"],
            "position": p["position"],
            "count": count,
            "owners": owners[pid],
        })
    rows.sort(key=lambda r: (-r["count"], r["name"]))
    return rows


def build_captains(league_managers, players, current_gw):
    rows = []
    for m in league_managers:
        picks, _ = latest_gw_data(m, current_gw)
        cap_id = picks["captain"] if picks else None
        p = players.get(str(cap_id)) or players.get(cap_id) if cap_id else None
        rows.append({
            "manager": m["label"],
            "team_name": m.get("team_name", ""),
            "captain_id": cap_id,
            "captain": p["name"] if p else None,
            "captain_team": p["team"] if p else None,
        })
    return rows


def build_transfers(league_managers, current_gw):
    rows = []
    for m in league_managers:
        picks, stats = latest_gw_data(m, current_gw)
        rows.append({
            "manager": m["label"],
            "transfers": stats["transfers"] if stats else 0,
            "transfer_cost": stats["transfer_cost"] if stats else 0,
            "gw_points": stats["points"] if stats else None,
            "active_chip": picks.get("active_chip") if picks else None,
            "chips_used": m.get("chips", []),
        })
    return rows


def build_standings(league_managers, current_gw):
    ranked = sorted(
        league_managers,
        key=lambda m: -(latest_gw_data(m, current_gw)[1] or {}).get("overall_rank", 0)
        if latest_gw_data(m, current_gw)[1] else 0,
    )
    # Rank by total points across the season (sum of gw points) instead, since
    # overall_rank direction is ascending (lower = better) -- resort properly.
    def total_points(m):
        return sum((s.get("points") or 0) for s in m["gw_stats"].values())

    ranked = sorted(league_managers, key=lambda m: -total_points(m))
    rows = []
    for i, m in enumerate(ranked, start=1):
        _, stats = latest_gw_data(m, current_gw)
        rows.append({
            "rank": i,
            "manager": m["label"],
            "team_name": m.get("team_name", ""),
            "entry_id": m["entry_id"],
            "total_points": total_points(m),
            "gw_points": stats["points"] if stats else None,
            "overall_rank": stats["overall_rank"] if stats else None,
        })
    return rows


def build_youtuber_comparisons(league_managers, youtuber_managers, current_gw):
    linked_labels = {y["label"] for y in youtuber_managers}
    youtubers_out = []
    for label in YOUTUBER_LABELS:
        match = next((y for y in youtuber_managers if y["label"] == label), None)
        if match is None:
            youtubers_out.append({"label": label, "linked": False})
            continue
        comps = []
        for lm in league_managers:
            common_gws = sorted(
                set(int(g) for g in lm["picks_by_gw"]) & set(int(g) for g in match["picks_by_gw"])
            )
            overlaps, cap_matches, cap_total = [], 0, 0
            for gw in common_gws:
                lp = lm["picks_by_gw"].get(str(gw)) or lm["picks_by_gw"].get(gw)
                yp = match["picks_by_gw"].get(str(gw)) or match["picks_by_gw"].get(gw)
                size = len(lp["squad"]) or len(yp["squad"])
                if size:
                    overlaps.append(len(set(lp["squad"]) & set(yp["squad"])) / size)
                if lp["captain"] and yp["captain"]:
                    cap_total += 1
                    if lp["captain"] == yp["captain"]:
                        cap_matches += 1
            comps.append({
                "manager": lm["label"],
                "avg_overlap": round(sum(overlaps) / len(overlaps), 3) if overlaps else None,
                "captain_match_pct": round(cap_matches / cap_total, 3) if cap_total else None,
                "gws_compared": len(common_gws),
            })
        youtubers_out.append({
            "label": label,
            "linked": True,
            "team_name": match.get("team_name", ""),
            "comparisons": comps,
        })
    return youtubers_out


def build_captain_leaderboard(league_managers, players, gw_live_points):
    def live_points_for(gw, pid):
        live = gw_live_points.get(str(gw)) or gw_live_points.get(gw) or {}
        return live.get(str(pid)) or live.get(pid) or 0

    rows = []
    for m in league_managers:
        total = 0
        gw_count = 0
        cap_counts = {}
        best_gw = None
        for gw_key, picks in m["picks_by_gw"].items():
            gw = int(gw_key)
            cap_id = picks.get("effective_captain")
            mult = picks.get("effective_multiplier") or 2
            if cap_id is None:
                continue
            contribution = live_points_for(gw, cap_id) * mult
            total += contribution
            gw_count += 1
            cap_counts[cap_id] = cap_counts.get(cap_id, 0) + 1
            if best_gw is None or contribution > best_gw["points"]:
                best_gw = {"gw": gw, "points": contribution}

        most_captained_id = max(cap_counts, key=cap_counts.get) if cap_counts else None
        p = (players.get(str(most_captained_id)) or players.get(most_captained_id)) if most_captained_id else None

        rows.append({
            "manager": m["label"],
            "team_name": m.get("team_name", ""),
            "total_captain_points": total,
            "gws": gw_count,
            "avg_per_gw": round(total / gw_count, 1) if gw_count else None,
            "most_captained": p["name"] if p else None,
            "most_captained_count": cap_counts.get(most_captained_id, 0) if most_captained_id else 0,
            "best_gw": best_gw,
        })

    rows.sort(key=lambda r: -r["total_captain_points"])
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def build_manager_profiles(league_managers, youtuber_managers, players, current_gw):
    def player_info(pid):
        p = players.get(str(pid)) or players.get(pid)
        if not p:
            return {"id": pid, "name": f"#{pid}", "team": "?", "position": "?"}
        return {"id": pid, "name": p["name"], "team": p["team"], "position": p["position"]}

    def profile(m, source):
        picks, stats = latest_gw_data(m, current_gw)
        squad = [player_info(pid) for pid in picks["squad"]] if picks else []
        starting_ids = set(picks.get("starting_xi", [])) if picks else set()
        starting_xi = [p for p in squad if p["id"] in starting_ids]
        cap_id = picks["captain"] if picks else None
        return {
            "id": f"{source}:{m['entry_id']}",
            "label": m["label"],
            "team_name": m.get("team_name", ""),
            "source": source,
            "squad": squad,
            "starting_xi": starting_xi,
            "captain": player_info(cap_id) if cap_id else None,
            "transfers": stats["transfers"] if stats else 0,
            "transfer_cost": stats["transfer_cost"] if stats else 0,
            "gw_points": stats["points"] if stats else None,
            "active_chip": picks.get("active_chip") if picks else None,
        }

    profiles = [profile(m, "league") for m in league_managers]
    profiles += [profile(m, "youtuber") for m in youtuber_managers]
    return profiles


def main():
    with open("fpl_data.json", encoding="utf-8") as f:
        data = json.load(f)

    league_managers = data["league_managers"]
    youtuber_managers = data["youtuber_managers"]
    players = data["players"]
    current_gw = data["current_gw"]
    gw_live_points = data.get("gw_live_points", {})

    out = {
        "league_name": data["league_name"],
        "current_gw": current_gw,
        "standings": build_standings(league_managers, current_gw),
        "overlap_matrix": build_within_league_overlap(league_managers, current_gw),
        "most_owned": build_most_owned(league_managers, players, current_gw),
        "captains": build_captains(league_managers, players, current_gw),
        "transfers": build_transfers(league_managers, current_gw),
        "youtubers": build_youtuber_comparisons(league_managers, youtuber_managers, current_gw),
        "captain_leaderboard": build_captain_leaderboard(league_managers, players, gw_live_points),
    }

    profiles = {
        "league_name": data["league_name"],
        "current_gw": current_gw,
        "managers": build_manager_profiles(league_managers, youtuber_managers, players, current_gw),
    }

    page_meta = {"current_gw": current_gw}

    with open("dashboard_data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    with open("compare_data.json", "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)
    with open("page_meta.json", "w", encoding="utf-8") as f:
        json.dump(page_meta, f, indent=2)

    print("Wrote dashboard_data.json, compare_data.json, and page_meta.json")
    print(json.dumps(out)[:200] + "...")


if __name__ == "__main__":
    main()
