"""
Fetch FPL data for a classic league and a set of "notable" managers (e.g. YouTubers),
then compute squad-overlap, captaincy-match and transfer/chip-timing comparisons.

Rerun this any time (e.g. after a new gameweek) to refresh fpl_data.json.
Then re-publish dashboard.html with the refreshed data.
"""
import json
import sys
import time
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://fantasy.premierleague.com/api"
LEAGUE_ID = 587101

# Fill in real entry IDs as you find them (see README.md for how).
# None = skipped until an ID is supplied.
YOUTUBERS = {
    "FPL Harry": None,
    "Let's Talk FPL": None,
    "FPL Focal": None,
    "FPL Raptor": None,
}

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (fpl-league-analysis script)"})


def get(url):
    r = session.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


POSITION_NAMES = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def fetch_bootstrap():
    data = get(f"{BASE}/bootstrap-static/")
    teams = {t["id"]: t["short_name"] for t in data["teams"]}
    players = {p["id"]: {
        "name": p["web_name"],
        "team": teams.get(p["team"], "?"),
        "position": POSITION_NAMES.get(p["element_type"], "?"),
    } for p in data["elements"]}
    events = data["events"]
    current_gw = next((e["id"] for e in events if e["is_current"]), None)
    if current_gw is None:
        finished = [e["id"] for e in events if e["is_finished"]]
        current_gw = max(finished) if finished else 1
    return players, current_gw


def fetch_league_entries(league_id):
    data = get(f"{BASE}/leagues-classic/{league_id}/standings/")
    league_name = data["league"]["name"]
    entries = []
    for row in data["standings"]["results"]:
        entries.append({
            "entry_id": row["entry"],
            "manager_name": row["player_name"],
            "team_name": row["entry_name"],
        })
    return league_name, entries


def fetch_entry_history(entry_id):
    return get(f"{BASE}/entry/{entry_id}/history/")


def fetch_entry_picks(entry_id, gw):
    return get(f"{BASE}/entry/{entry_id}/event/{gw}/picks/")


def build_manager_record(entry_id, label, current_gw):
    history = fetch_entry_history(entry_id)
    chips = [{"name": c["name"], "event": c["event"]} for c in history.get("chips", [])]

    gw_transfers = {}
    for h in history.get("current", []):
        gw_transfers[h["event"]] = {
            "points": h["points"],
            "transfers": h["event_transfers"],
            "transfer_cost": h["event_transfers_cost"],
            "overall_rank": h["overall_rank"],
        }

    picks_by_gw = {}
    played_gws = sorted(gw_transfers.keys())
    for gw in played_gws:
        try:
            p = fetch_entry_picks(entry_id, gw)
        except requests.HTTPError:
            continue
        squad = [pk["element"] for pk in p["picks"]]
        starting_xi = [pk["element"] for pk in p["picks"] if pk["position"] <= 11]
        captain = next((pk["element"] for pk in p["picks"] if pk["is_captain"]), None)
        picks_by_gw[gw] = {
            "squad": squad,
            "starting_xi": starting_xi,
            "captain": captain,
            "active_chip": p.get("active_chip"),
        }
        time.sleep(0.15)  # be polite to the API

    return {
        "entry_id": entry_id,
        "label": label,
        "chips": chips,
        "gw_stats": gw_transfers,
        "picks_by_gw": picks_by_gw,
    }


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a or not b:
        return None
    return len(a & b) / len(a | b)


def compute_comparisons(league_managers, youtuber_managers):
    comparisons = []
    for lm in league_managers:
        for ym in youtuber_managers:
            common_gws = sorted(set(lm["picks_by_gw"]) & set(ym["picks_by_gw"]))
            overlaps = []
            captain_matches = 0
            captain_total = 0
            for gw in common_gws:
                lp = lm["picks_by_gw"][gw]
                yp = ym["picks_by_gw"][gw]
                ov = jaccard(lp["squad"], yp["squad"])
                if ov is not None:
                    overlaps.append(ov)
                if lp["captain"] is not None and yp["captain"] is not None:
                    captain_total += 1
                    if lp["captain"] == yp["captain"]:
                        captain_matches += 1
            comparisons.append({
                "league_entry": lm["entry_id"],
                "youtuber_entry": ym["entry_id"],
                "avg_squad_overlap": sum(overlaps) / len(overlaps) if overlaps else None,
                "latest_squad_overlap": overlaps[-1] if overlaps else None,
                "captain_match_pct": (captain_matches / captain_total) if captain_total else None,
                "gws_compared": len(common_gws),
            })
    return comparisons


def main():
    print("Fetching bootstrap data...")
    players, current_gw = fetch_bootstrap()
    print(f"Current/latest finished gameweek: {current_gw}")

    print(f"Fetching league {LEAGUE_ID} standings...")
    league_name, entries = fetch_league_entries(LEAGUE_ID)
    print(f"League: {league_name} ({len(entries)} managers)")

    league_managers = []
    for e in entries:
        print(f"  Fetching {e['manager_name']} ({e['entry_id']})...")
        rec = build_manager_record(e["entry_id"], e["manager_name"], current_gw)
        rec["team_name"] = e["team_name"]
        league_managers.append(rec)
        time.sleep(0.2)

    youtuber_managers = []
    for label, entry_id in YOUTUBERS.items():
        if entry_id is None:
            print(f"  Skipping {label} (no entry ID set yet)")
            continue
        print(f"  Fetching {label} ({entry_id})...")
        rec = build_manager_record(entry_id, label, current_gw)
        youtuber_managers.append(rec)
        time.sleep(0.2)

    comparisons = compute_comparisons(league_managers, youtuber_managers)

    out = {
        "league_id": LEAGUE_ID,
        "league_name": league_name,
        "current_gw": current_gw,
        "players": players,
        "league_managers": league_managers,
        "youtuber_managers": youtuber_managers,
        "comparisons": comparisons,
    }

    with open("fpl_data.json", "w", encoding="utf-8") as f:
        json.dump(out, f)

    print(f"\nWrote fpl_data.json ({len(league_managers)} league managers, "
          f"{len(youtuber_managers)} youtubers, {len(comparisons)} comparisons)")


if __name__ == "__main__":
    main()
