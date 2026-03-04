import os
import csv
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
import spotipy
from spotipy.oauth2 import SpotifyOAuth

app = Flask(__name__)

# ── Config (set these as Railway environment variables) ──────────────────────
SPOTIFY_CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
SPOTIFY_REDIRECT_URI  = os.environ["SPOTIFY_REDIRECT_URI"]   # e.g. https://your-app.railway.app/callback
SPOTIFY_USER_ID       = os.environ["SPOTIFY_USER_ID"]        # your Spotify user ID

LASTFM_API_KEY        = os.environ["LASTFM_API_KEY"]
LASTFM_USERNAME       = os.environ["LASTFM_USERNAME"]

CSV_PATH              = os.environ.get("CSV_PATH", "LOUNGE.csv")
EXCLUDE_DAYS          = int(os.environ.get("EXCLUDE_DAYS", "30"))   # exclude tracks played within N days
QUEUE_SIZE            = int(os.environ.get("QUEUE_SIZE", "200"))    # tracks in output playlist
LASTFM_PAGES          = int(os.environ.get("LASTFM_PAGES", "50"))   # pages × 200 = scrobbles fetched

# ── Spotify auth ─────────────────────────────────────────────────────────────
SCOPE = "playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public"

def get_spotify():
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SCOPE,
        cache_path=".spotify_cache"
    ))

# ── OAuth callback (needed for first-time token) ─────────────────────────────
@app.route("/callback")
def callback():
    sp = get_spotify()
    return jsonify({"status": "✅ Spotify auth successful! You can now call /run"})

# ── Load playlist from CSV ────────────────────────────────────────────────────
def load_playlist_csv(path):
    tracks = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uri = row.get("Track URI", "").strip()
            name = row.get("Track Name", "").strip()
            # Artist Name(s) can be semicolon-separated — take first
            artists_raw = row.get("Artist Name(s)", "").strip()
            artist = artists_raw.split(";")[0].strip()
            if uri and name and artist:
                tracks.append({
                    "uri": uri,
                    "name": name,
                    "artist": artist,
                    "artist_key": artist.lower(),
                    "name_key": name.lower(),
                })
    return tracks

# ── Fetch Last.fm play history ────────────────────────────────────────────────
def fetch_lastfm_history():
    two_years_ago = int((datetime.now() - timedelta(days=730)).timestamp())
    play_history = {}  # "artist|||track" → latest timestamp

    for page in range(1, LASTFM_PAGES + 1):
        url = (
            f"https://ws.audioscrobbler.com/2.0/"
            f"?method=user.getrecenttracks"
            f"&user={LASTFM_USERNAME}"
            f"&api_key={LASTFM_API_KEY}"
            f"&format=json"
            f"&limit=200"
            f"&page={page}"
            f"&from={two_years_ago}"
        )
        resp = requests.get(url, timeout=15)
        data = resp.json()

        tracks = data.get("recenttracks", {}).get("track", [])
        total_pages = int(data.get("recenttracks", {}).get("@attr", {}).get("totalPages", 1))

        for t in tracks:
            if isinstance(t.get("@attr"), dict) and t["@attr"].get("nowplaying"):
                continue
            artist = t.get("artist", {}).get("#text", "").lower()
            name   = t.get("name", "").lower()
            uts    = t.get("date", {}).get("uts")
            if artist and name and uts:
                key = f"{artist}|||{name}"
                ts = int(uts)
                if key not in play_history or ts > play_history[key]:
                    play_history[key] = ts

        if page >= total_pages:
            break
        time.sleep(0.25)  # be nice to Last.fm API

    return play_history

# ── Core logic ────────────────────────────────────────────────────────────────
def build_smart_queue(tracks, play_history):
    now = int(time.time())
    recent_cutoff = now - (EXCLUDE_DAYS * 86400)

    enriched = []
    for t in tracks:
        key = f"{t['artist_key']}|||{t['name_key']}"
        last_played = play_history.get(key)
        played_recently = last_played is not None and last_played > recent_cutoff

        enriched.append({
            **t,
            "last_played": last_played,
            "never_played": last_played is None,
            "played_recently": played_recently,
            "days_ago": int((now - last_played) / 86400) if last_played else None,
        })

    # Exclude recently played
    eligible = [t for t in enriched if not t["played_recently"]]

    # Sort: never played first, then oldest played first
    eligible.sort(key=lambda t: (
        0 if t["never_played"] else 1,
        t["last_played"] if t["last_played"] else 0
    ))

    selected = eligible[:QUEUE_SIZE]

    stats = {
        "total_in_playlist": len(tracks),
        "never_played": sum(1 for t in enriched if t["never_played"]),
        "played_recently_excluded": sum(1 for t in enriched if t["played_recently"]),
        "eligible": len(eligible),
        "selected": len(selected),
    }

    return selected, stats

# ── Create Spotify playlist ───────────────────────────────────────────────────
def create_spotify_playlist(sp, selected_tracks, stats):
    week_num = datetime.now().isocalendar()[1]
    date_str = datetime.now().strftime("%Y-%m-%d")
    name = f"🎵 Smart Queue – Week {week_num} ({date_str})"
    description = (
        f"Never heard: {stats['never_played']} | "
        f"Excluded (last {EXCLUDE_DAYS}d): {stats['played_recently_excluded']} | "
        f"Eligible: {stats['eligible']}"
    )

    playlist = sp.user_playlist_create(
        user=SPOTIFY_USER_ID,
        name=name,
        public=False,
        description=description
    )
    playlist_id = playlist["id"]

    # Add tracks in batches of 100
    uris = [t["uri"] for t in selected_tracks]
    for i in range(0, len(uris), 100):
        sp.playlist_add_items(playlist_id, uris[i:i+100])

    return playlist["external_urls"]["spotify"], name

# ── Main endpoint ─────────────────────────────────────────────────────────────
@app.route("/run")
def run():
    try:
        print("📂 Loading playlist CSV...")
        tracks = load_playlist_csv(CSV_PATH)
        print(f"   {len(tracks)} tracks loaded")

        print("🎵 Fetching Last.fm history...")
        play_history = fetch_lastfm_history()
        print(f"   {len(play_history)} unique tracks in history")

        print("🔀 Building smart queue...")
        selected, stats = build_smart_queue(tracks, play_history)
        print(f"   Stats: {stats}")

        print("📋 Creating Spotify playlist...")
        sp = get_spotify()
        playlist_url, playlist_name = create_spotify_playlist(sp, selected, stats)
        print(f"   Created: {playlist_url}")

        return jsonify({
            "status": "✅ Success",
            "playlist_name": playlist_name,
            "playlist_url": playlist_url,
            "stats": stats,
            "top_10_tracks": [
                {"artist": t["artist"], "name": t["name"], "days_ago": t["days_ago"]}
                for t in selected[:10]
            ]
        })

    except Exception as e:
        return jsonify({"status": "❌ Error", "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
