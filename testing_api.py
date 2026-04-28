import httpx
from datetime import datetime

URLS = [
    "https://www.cricbuzz.com/api/cricket-match-list/v1/live",
    "https://www.cricbuzz.com/api/cricket-match-list/v1/recent"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.cricbuzz.com/",
    "Accept": "application/json"
}


def fetch_json(url):
    try:
        with httpx.Client(http2=True, timeout=10.0) as client:
            res = client.get(url, headers=HEADERS)

            if res.status_code != 200:
                return None

            if "json" not in res.headers.get("content-type", ""):
                return None

            return res.json()

    except Exception:
        return None


def extract_ipl_matches(data):
    matches = []

    for t in data.get("typeMatches", []):
        for s in t.get("seriesMatches", []):
            wrapper = s.get("seriesAdWrapper")
            if not wrapper:
                continue

            if "Indian Premier League" not in wrapper.get("seriesName", ""):
                continue

            for m in wrapper.get("matches", []):
                info = m["matchInfo"]

                matches.append({
                    "id": info["matchId"],
                    "teams": f"{info['team1']['teamName']} vs {info['team2']['teamName']}",
                    "status": info["status"],
                    "start": int(info["startDate"])
                })

    return matches


def get_latest_ipl_match():
    for url in URLS:
        data = fetch_json(url)
        if not data:
            continue

        matches = extract_ipl_matches(data)

        if matches:
            matches.sort(key=lambda x: x["start"], reverse=True)
            return matches[0]

    return None


def pretty_print(match):
    dt = datetime.fromtimestamp(match["start"] / 1000)

    print("\n🏏 Latest IPL Match\n")
    print(f"Teams   : {match['teams']}")
    print(f"Time    : {dt}")
    print(f"Status  : {match['status']}")
    print(f"Match ID: {match['id']}")
    print(f"\n👉 API  : https://www.cricbuzz.com/api/mcenter/comm/{match['id']}\n")


if __name__ == "__main__":
    match = get_latest_ipl_match()

    if not match:
        print("❌ Could not fetch IPL match (blocked or no data)")
    else:
        pretty_print(match)