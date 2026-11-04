#!/usr/bin/env python3
"""Generate a compact Steam statistics card for the GitHub profile README."""

import base64
import concurrent.futures
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.steampowered.com"
API_KEY = os.environ.get("STEAM_API_KEY", "").strip()
VANITY = os.environ.get("STEAM_VANITY_URL", "Velzinha").strip()
OUT = Path("assets/steam-stats.svg")
TIMEOUT = 30


def api_get(interface, method, params, version="v1"):
    query = urllib.parse.urlencode(params)
    url = f"{API}/{interface}/{method}/{version}/?{query}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "Velquis-Steam-Stats/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Steam API request failed ({method}): {exc}") from exc


def resolve_steam_id():
    data = api_get(
        "ISteamUser",
        "ResolveVanityURL",
        {"key": API_KEY, "vanityurl": VANITY},
    )
    result = data.get("response", {})
    if result.get("success") != 1 or not result.get("steamid"):
        raise RuntimeError(
            f"Could not resolve Steam profile '{VANITY}'. Check the vanity URL."
        )
    return result["steamid"]


def get_player_profile(steam_id):
    data = api_get(
        "ISteamUser",
        "GetPlayerSummaries",
        {"key": API_KEY, "steamids": steam_id},
        version="v2",
    )
    players = data.get("response", {}).get("players", [])
    if not players:
        raise RuntimeError("Steam did not return profile details for this account.")
    player = players[0]
    avatar_url = player.get("avatarfull") or player.get("avatarmedium") or player.get("avatar")
    if not avatar_url:
        raise RuntimeError("Steam did not return a profile avatar.")
    # Prefer embedding the avatar bytes, but do not fail the whole stats update
    # if Steam's image CDN temporarily rejects the download.
    avatar_reference = avatar_url
    request = urllib.request.Request(
        avatar_url, headers={"User-Agent": "Mozilla/5.0 (compatible; Velquis-Steam-Stats/1.0)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            avatar_bytes = response.read()
            content_type = response.headers.get("Content-Type", "image/jpeg")
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"
        avatar_data = base64.b64encode(avatar_bytes).decode("ascii")
        avatar_reference = f"data:{content_type};base64,{avatar_data}"
        print("Steam avatar downloaded successfully.")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"WARNING: Could not download Steam avatar ({exc!r}); using its public URL.")
    return {
        "name": player.get("personaname", "Steam Player"),
        "profile_url": player.get("profileurl", "https://steamcommunity.com/"),
        "avatar_data_uri": avatar_reference,
    }


def get_game_cover(app_id):
    cover_url = f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
    request = urllib.request.Request(
        cover_url, headers={"User-Agent": "Mozilla/5.0 (compatible; Velquis-Steam-Stats/1.0)"}
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            image_bytes = response.read()
            content_type = response.headers.get("Content-Type", "image/jpeg")
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"WARNING: cover unavailable for app {app_id}: {exc!r}")
        return cover_url


def get_owned_games(steam_id):
    data = api_get(
        "IPlayerService",
        "GetOwnedGames",
        {
            "key": API_KEY,
            "steamid": steam_id,
            "include_appinfo": 1,
            "include_played_free_games": 1,
        },
    )
    response = data.get("response", {})
    if "games" not in response:
        raise RuntimeError(
            "Steam returned no game list. Confirm that Game details is Public."
        )
    return response["games"]


def inspect_game(game, steam_id):
    app_id = game["appid"]
    common = {"key": API_KEY, "appid": app_id}

    try:
        schema_data = api_get(
            "ISteamUserStats", "GetSchemaForGame", common
        )
        available = (
            schema_data.get("game", {})
            .get("availableGameStats", {})
            .get("achievements", [])
        )
        if not available:
            return None

        player_data = api_get(
            "ISteamUserStats",
            "GetPlayerAchievements",
            {**common, "steamid": steam_id},
        )
        playerstats = player_data.get("playerstats", {})
        if not playerstats.get("success"):
            return None

        achievements = playerstats.get("achievements", [])
        if not achievements:
            return None

        unlocked = sum(1 for item in achievements if item.get("achieved") == 1)
        total = len(available)
        return {
            "app_id": app_id,
            "name": game.get("name", f"App {app_id}"),
            "unlocked": unlocked,
            "total": total,
            "perfect": unlocked == total,
        }
    except RuntimeError:
        return None


def svg_card(stats, profile):
    values = [
        (f"{stats['perfect_games']}", "PERFECT GAMES"),
        (f"{stats['total_games']}", "GAMES OWNED"),
        (f"{stats['unlocked']:,}", "ACHIEVEMENTS"),
        (f"{stats['hours']:,}", "HOURS PLAYED"),
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1120" height="460" viewBox="0 0 1120 460">',
        '<rect width="1120" height="460" rx="18" fill="#171717"/>',
        '<defs><clipPath id="avatarCircle"><circle cx="134.5" cy="160.5" r="72.5"/></clipPath></defs>',
        '<rect x="0" y="0" width="1120" height="5" rx="2" fill="#ffb6d9"/>',
        '<text x="38" y="45" fill="#ffb6d9" font-family="Arial, sans-serif" font-size="12" font-weight="700" letter-spacing="2">STEAM PROFILE</text>',
        '<text x="1080" y="45" text-anchor="end" fill="#777777" font-family="Arial, sans-serif" font-size="11" letter-spacing="1">LIVE PROFILE DATA</text>',
        '<line x1="270" y1="72" x2="270" y2="270" stroke="#303030" stroke-width="1"/>',
        f'<a xlink:href="{html.escape(profile["profile_url"], quote=True)}"><image xlink:href="{profile["avatar_data_uri"]}" x="62" y="88" width="145" height="145" preserveAspectRatio="xMidYMid slice" clip-path="url(#avatarCircle)"/></a>',
        '<circle cx="134.5" cy="160.5" r="72.5" fill="none" stroke="#ffb6d9" stroke-width="3"/>',
        f'<text x="134" y="267" text-anchor="middle" fill="#ffffff" font-family="Arial, sans-serif" font-size="22" font-weight="700">{html.escape(profile["name"])}</text>',
        '<text x="134" y="290" text-anchor="middle" fill="#ffb6d9" font-family="Arial, sans-serif" font-size="11" font-weight="700" letter-spacing="2">STEAM PLAYER</text>',
        '<text x="310" y="92" fill="#aaaaaa" font-family="Arial, sans-serif" font-size="12" font-weight="700" letter-spacing="1.8">PLAYER OVERVIEW</text>',
    ]
    badge_positions = [300, 496, 692, 888]
    for (value, label), x in zip(values, badge_positions):
        parts.extend([
            f'<rect x="{x}" y="112" width="176" height="112" rx="16" fill="#202020" stroke="#343434" stroke-width="1.5"/>',
            f'<rect x="{x + 14}" y="126" width="148" height="3" rx="1.5" fill="#ffb6d9" opacity="0.75"/>',
            f'<text x="{x + 88}" y="178" text-anchor="middle" fill="#ffb6d9" font-family="Arial, sans-serif" font-size="43" font-weight="700">{html.escape(value)}</text>',
            f'<text x="{x + 88}" y="202" text-anchor="middle" fill="#c5c5c5" font-family="Arial, sans-serif" font-size="10" font-weight="700" letter-spacing="1">{label}</text>',
        ])
    parts.extend([
        '<line x1="300" y1="244" x2="1080" y2="244" stroke="#303030" stroke-width="1"/>',
        '<text x="38" y="345" fill="#ffb6d9" font-family="Arial, sans-serif" font-size="12" font-weight="700" letter-spacing="2">MOST PLAYED GAMES</text>',
    ])
    game_positions = [38, 405, 772]
    for game, x in zip(stats.get("top_games", []), game_positions):
        name = html.escape(game["name"])
        hours = f'{game["hours"]:,} HRS'
        cover = game["cover"]
        parts.extend([
            f'<rect x="{x}" y="362" width="330" height="82" rx="10" fill="#202020"/>',
            f'<image xlink:href="{cover}" x="{x + 8}" y="370" width="132" height="66" preserveAspectRatio="xMidYMid slice"/>',
            f'<text x="{x + 152}" y="395" fill="#ffffff" font-family="Arial, sans-serif" font-size="14" font-weight="700">{name[:28]}</text>',
            f'<text x="{x + 152}" y="419" fill="#ffb6d9" font-family="Arial, sans-serif" font-size="11" font-weight="700" letter-spacing="1">{hours}</text>',
        ])
    if not stats.get("top_games"):
        parts.append('<text x="38" y="395" fill="#aaaaaa" font-family="Arial, sans-serif" font-size="13">No playtime data available yet.</text>')
    parts.extend([
        '<text x="38" y="454" fill="#666666" font-family="Arial, sans-serif" font-size="9">AUTO-SYNCED WITH STEAM</text>',
        '<text x="1080" y="454" text-anchor="end" fill="#666666" font-family="Arial, sans-serif" font-size="9">GITHUB ACTIONS</text>',
        '</svg>',
    ])
    return "\n".join(parts)


def main():
    if not API_KEY:
        raise RuntimeError("Missing STEAM_API_KEY. Add it to repository Actions secrets.")

    steam_id = resolve_steam_id()
    profile = get_player_profile(steam_id)
    games = get_owned_games(steam_id)
    total_games = len(games)
    total_minutes = sum(game.get("playtime_forever", 0) for game in games)

    print(f"Found {total_games} owned games. Checking achievement completion...")
    results = []
    # Keep concurrency low to avoid overwhelming Steam's public API.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(inspect_game, game, steam_id) for game in games]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            result = future.result()
            if result:
                results.append(result)
            if index % 25 == 0 or index == total_games:
                print(f"Checked {index}/{total_games} games")

    top_games = sorted(
        [game for game in games if game.get("playtime_forever", 0) > 0],
        key=lambda game: game.get("playtime_forever", 0),
        reverse=True,
    )[:3]
    top_games_display = []
    for game in top_games:
        top_games_display.append({
            "app_id": game["appid"],
            "name": game.get("name", f"App {game['appid']}"),
            "hours": round(game.get("playtime_forever", 0) / 60),
            "cover": get_game_cover(game["appid"]),
        })

    perfect_games = sum(1 for item in results if item["perfect"])
    unlocked = sum(item["unlocked"] for item in results)
    total_achievements = sum(item["total"] for item in results)
    stats = {
        "steam_id": steam_id,
        "total_games": total_games,
        "hours": round(total_minutes / 60),
        "perfect_games": perfect_games,
        "unlocked": unlocked,
        "total_achievements": total_achievements,
        "games_with_achievement_data": len(results),
        "perfect_game_list": sorted(
            [item["name"] for item in results if item["perfect"]],
            key=str.casefold,
        ),
        "top_games": top_games_display,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg_card(stats, profile), encoding="utf-8")
    Path("assets/steam-stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Done: {perfect_games} perfect games, {total_games} owned games, "
        f"{stats['hours']} hours, {unlocked}/{total_achievements} achievements."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
