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


def api_get(interface, method, params):
    query = urllib.parse.urlencode(params)
    url = f"{API}/{interface}/{method}/v1/?{query}"
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
    )
    players = data.get("response", {}).get("players", [])
    if not players:
        raise RuntimeError("Steam did not return profile details for this account.")
    player = players[0]
    avatar_url = player.get("avatarfull") or player.get("avatarmedium") or player.get("avatar")
    if not avatar_url:
        raise RuntimeError("Steam did not return a profile avatar.")
    request = urllib.request.Request(
        avatar_url, headers={"User-Agent": "Velquis-Steam-Stats/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            avatar_bytes = response.read()
            content_type = response.headers.get("Content-Type", "image/jpeg")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not download Steam avatar: {exc}") from exc
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    avatar_data = base64.b64encode(avatar_bytes).decode("ascii")
    return {
        "name": player.get("personaname", "Steam Player"),
        "profile_url": player.get("profileurl", "https://steamcommunity.com/"),
        "avatar_data_uri": f"data:{content_type};base64,{avatar_data}",
    }


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
        '<svg xmlns="http://www.w3.org/2000/svg" width="960" height="190" viewBox="0 0 960 190">',
        '<rect width="960" height="190" rx="14" fill="#171717"/>',
        '<rect x="0" y="0" width="960" height="4" rx="2" fill="#ffb6d9"/>',
        f'<a href="{html.escape(profile["profile_url"], quote=True)}"><image href="{profile["avatar_data_uri"]}" x="32" y="18" width="58" height="58" preserveAspectRatio="xMidYMid slice"/></a>',
        '<rect x="32" y="18" width="58" height="58" rx="12" fill="none" stroke="#ffb6d9" stroke-width="2"/>',
        f'<text x="108" y="43" fill="#ffffff" font-family="Arial, sans-serif" font-size="17" font-weight="700">{html.escape(profile["name"])}</text>',
        '<text x="108" y="63" fill="#ffb6d9" font-family="Arial, sans-serif" font-size="10" font-weight="700" letter-spacing="1.5">STEAM PLAYER</text>',
        '<text x="928" y="42" text-anchor="end" fill="#8b949e" font-family="Arial, sans-serif" font-size="11">LIVE PROFILE DATA</text>',
    ]
    positions = [32, 267, 502, 737]
    for index, ((value, label), x) in enumerate(zip(values, positions)):
        parts.append(
            f'<text x="{x}" y="112" fill="#ffb6d9" font-family="Arial, sans-serif" font-size="42" font-weight="700">{html.escape(value)}</text>'
        )
        parts.append(
            f'<text x="{x}" y="140" fill="#a1a1aa" font-family="Arial, sans-serif" font-size="11" letter-spacing="1.3">{label}</text>'
        )
        if index < 3:
            parts.append(
                f'<line x1="{x + 205}" y1="72" x2="{x + 205}" y2="150" stroke="#292929" stroke-width="1"/>'
            )
    parts.extend([
        '<text x="32" y="174" fill="#6e7681" font-family="Arial, sans-serif" font-size="10">AUTO-SYNCED WITH STEAM</text>',
        '<text x="928" y="174" text-anchor="end" fill="#6e7681" font-family="Arial, sans-serif" font-size="10">GITHUB ACTIONS</text>',
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
