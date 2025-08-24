#!/usr/bin/env python3
import argparse
import csv
import os
import sys
import time
from typing import Dict, List, Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException

REDIRECT_URI_DEFAULT = "http://127.0.0.1:8080/callback"
SCOPE = "playlist-read-private playlist-read-collaborative user-library-read"

def load_secrets():
    secrets_file = ".api_secrets"
    if not os.path.exists(secrets_file):
        return None, None
    client_id = None
    client_secret = None
    with open(secrets_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    value = value.strip().strip("\"'")
                    if key == "SPOTIFY_CLIENT_ID" and value:
                        client_id = value
                    elif key == "SPOTIFY_CLIENT_SECRET" and value:
                        client_secret = value
    if client_id and client_secret:
        return client_id, client_secret
    else:
        return None, None

def backoff_sleep(retry_count: int, base: float = 0.5, cap: float = 8.0):
    sleep = min(cap, base * (2**retry_count))
    time.sleep(sleep)

class SpotifyPlaylistExporter:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = REDIRECT_URI_DEFAULT,
        username: str = "me",
        reauth: bool = False,
    ):
        """
        username is an arbitrary label used both for token cache and for file prefixing.
        Use a stable identifier (e.g., actual Spotify user ID or a nickname you choose).
        """
        cache_path = f".cache-{username}"
        self.username = username
        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=SCOPE,
                cache_path=cache_path,
                open_browser=True,
                show_dialog=reauth or not os.path.exists(cache_path),  # <= force account chooser
            )
        )

        # fetch and record the real authenticated user
        me = self.sp.current_user()
        if me:
            self.authenticated_user_id = me.get("id")
            self.authenticated_display_name = (me.get("display_name") or self.authenticated_user_id)
        else:
            self.authenticated_user_id = None
            self.authenticated_display_name = None
        print(f"[{self.username}] Authenticated as Spotify user: {self.authenticated_display_name}")

    # ---------- playlist helpers ----------
    def get_user_playlists(self) -> List[dict]:
        playlists = []
        results = self._retry(lambda: self.sp.current_user_playlists())
        while results:
            playlists.extend(results["items"])
            if results.get("next"):
                results = self._retry(lambda: self.sp.next(results))
            else:
                break
        return playlists

    def list_playlists(self) -> List[dict]:
        playlists = self.get_user_playlists()
        liked_songs_info = self._retry(lambda: self.sp.current_user_saved_tracks(limit=1))
        liked_songs_count = liked_songs_info.get('total', 0) if liked_songs_info else 0
        print(f"[{self.username}] Found {len(playlists) + 1} playlists:")
        print(f" 1. Liked Songs ({liked_songs_count} tracks) [Special Collection]")
        for i, p in enumerate(playlists, 2):
            print(f"{i:2d}. {p['name']} ({p['tracks']['total']} tracks)")
        return playlists

    def find_playlist_by_name(self, playlist_name: str) -> Optional[dict]:
        if playlist_name.lower() in ["liked songs", "liked", "saved songs", "saved"]:
            return {"id": "LIKED_SONGS", "name": "Liked Songs", "tracks": {"total": -1}}
        for playlist in self.get_user_playlists():
            if playlist["name"].lower() == playlist_name.lower():
                return playlist
        return None

    # ---------- Liked Songs support ----------
    def get_liked_songs(self, fetch_features: bool = True) -> List[dict]:
        tracks: List[dict] = []
        raw_items: List[dict] = []
        print(f"[{self.username}] Fetching liked songs...")
        results = self._retry(lambda: self.sp.current_user_saved_tracks(limit=50))
        total = results.get('total', 0) if results else 0
        print(f"[{self.username}] Total liked songs: {total}")
        while results:
            raw_items.extend(results["items"])
            print(f"[{self.username}]   Fetched {len(raw_items)}/{total} songs...")
            if results.get("next"):
                results = self._retry(lambda: self.sp.next(results))
            else:
                break

        valid_ids: List[str] = []
        for item in raw_items:
            tr = item.get("track")
            if not tr or tr.get("is_local") or not tr.get("id"):
                continue
            valid_ids.append(tr["id"])

        features_by_id: Dict[str, Optional[dict]] = {}
        if fetch_features and valid_ids:
            print(f"[{self.username}] Fetching audio features for {len(valid_ids)} tracks...")
            for i in range(0, len(valid_ids), 100):
                batch = valid_ids[i : i + 100]
                def _get_feats():
                    return self.sp.audio_features(batch)
                feats_list = self._retry(_get_feats, swallow_statuses={403})
                for tid, feats in zip(batch, feats_list or [None] * len(batch)):
                    features_by_id[tid] = feats

        for item in raw_items:
            tr = item.get("track")
            if not tr or tr.get("is_local") or not tr.get("id"):
                continue
            dur_ms = tr.get("duration_ms") or 0
            track_row = {
                "track_name": tr.get("name", ""),
                "artist_names": ", ".join(
                    a["name"] for a in tr.get("artists", []) if a and a.get("name")
                ),
                "album_name": tr.get("album", {}).get("name", ""),
                "album_type": tr.get("album", {}).get("album_type", ""),
                "release_date": tr.get("album", {}).get("release_date", ""),
                "duration_ms": dur_ms,
                "duration_min_sec": f"{dur_ms // 60000}:{(dur_ms % 60000) // 1000:02d}",
                "popularity": tr.get("popularity", ""),
                "explicit": tr.get("explicit", ""),
                "track_number": tr.get("track_number", ""),
                "disc_number": tr.get("disc_number", ""),
                "spotify_id": tr.get("id", ""),
                "spotify_url": tr.get("external_urls", {}).get("spotify", ""),
                "preview_url": tr.get("preview_url") or "",
                "added_at": item.get("added_at", ""),
                "added_by": self.username,
            }
            feats = features_by_id.get(tr["id"]) if fetch_features else None
            if feats:
                track_row.update(
                    {
                        "danceability": feats.get("danceability", ""),
                        "energy": feats.get("energy", ""),
                        "key": feats.get("key", ""),
                        "loudness": feats.get("loudness", ""),
                        "mode": feats.get("mode", ""),
                        "speechiness": feats.get("speechiness", ""),
                        "acousticness": feats.get("acousticness", ""),
                        "instrumentalness": feats.get("instrumentalness", ""),
                        "liveness": feats.get("liveness", ""),
                        "valence": feats.get("valence", ""),
                        "tempo": feats.get("tempo", ""),
                        "time_signature": feats.get("time_signature", ""),
                    }
                )
            else:
                track_row.update(
                    {
                        "danceability": "",
                        "energy": "",
                        "key": "",
                        "loudness": "",
                        "mode": "",
                        "speechiness": "",
                        "acousticness": "",
                        "instrumentalness": "",
                        "liveness": "",
                        "valence": "",
                        "tempo": "",
                        "time_signature": "",
                    }
                )
            tracks.append(track_row)
        return tracks

    # ---------- tracks & audio features ----------
    def get_playlist_tracks(
        self, playlist_id: str, fetch_features: bool = True
    ) -> List[dict]:
        tracks: List[dict] = []
        raw_items: List[dict] = []

        results = self._retry(lambda: self.sp.playlist_tracks(playlist_id))
        while results:
            raw_items.extend(results["items"])
            if results.get("next"):
                results = self._retry(lambda: self.sp.next(results))
            else:
                break

        valid_ids: List[str] = []
        for item in raw_items:
            tr = item.get("track")
            if not tr:
                continue
            if tr.get("is_local"):
                continue
            if tr.get("type") != "track":
                continue
            if not tr.get("id"):
                continue
            valid_ids.append(tr["id"])

        features_by_id: Dict[str, Optional[dict]] = {}
        if fetch_features and valid_ids:
            for i in range(0, len(valid_ids), 100):
                batch = valid_ids[i : i + 100]
                def _get_feats():
                    return self.sp.audio_features(batch)
                feats_list = self._retry(_get_feats, swallow_statuses={403})
                for tid, feats in zip(batch, feats_list or [None] * len(batch)):
                    features_by_id[tid] = feats

        for item in raw_items:
            tr = item.get("track")
            if (
                not tr
                or tr.get("is_local")
                or tr.get("type") != "track"
                or not tr.get("id")
            ):
                continue

            dur_ms = tr.get("duration_ms") or 0
            track_row = {
                "track_name": tr.get("name", ""),
                "artist_names": ", ".join(
                    a["name"] for a in tr.get("artists", []) if a and a.get("name")
                ),
                "album_name": tr.get("album", {}).get("name", ""),
                "album_type": tr.get("album", {}).get("album_type", ""),
                "release_date": tr.get("album", {}).get("release_date", ""),
                "duration_ms": dur_ms,
                "duration_min_sec": f"{dur_ms // 60000}:{(dur_ms % 60000) // 1000:02d}",
                "popularity": tr.get("popularity", ""),
                "explicit": tr.get("explicit", ""),
                "track_number": tr.get("track_number", ""),
                "disc_number": tr.get("disc_number", ""),
                "spotify_id": tr.get("id", ""),
                "spotify_url": tr.get("external_urls", {}).get("spotify", ""),
                "preview_url": tr.get("preview_url") or "",
                "added_at": item.get("added_at", ""),
                "added_by": (item.get("added_by") or {}).get("id", ""),
            }

            feats = features_by_id.get(tr["id"]) if fetch_features else None
            if feats:
                track_row.update(
                    {
                        "danceability": feats.get("danceability", ""),
                        "energy": feats.get("energy", ""),
                        "key": feats.get("key", ""),
                        "loudness": feats.get("loudness", ""),
                        "mode": feats.get("mode", ""),
                        "speechiness": feats.get("speechiness", ""),
                        "acousticness": feats.get("acousticness", ""),
                        "instrumentalness": feats.get("instrumentalness", ""),
                        "liveness": feats.get("liveness", ""),
                        "valence": feats.get("valence", ""),
                        "tempo": feats.get("tempo", ""),
                        "time_signature": feats.get("time_signature", ""),
                    }
                )
            else:
                track_row.update(
                    {
                        "danceability": "",
                        "energy": "",
                        "key": "",
                        "loudness": "",
                        "mode": "",
                        "speechiness": "",
                        "acousticness": "",
                        "instrumentalness": "",
                        "liveness": "",
                        "valence": "",
                        "tempo": "",
                        "time_signature": "",
                    }
                )

            tracks.append(track_row)
        return tracks

    # ---------- CSV ----------
    @staticmethod
    def _safe_filename(name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).rstrip()
        return f"{safe}.csv" if not safe.endswith(".csv") else safe

    def _prefixed_path(self, base_name: str) -> str:
        """Return data/<username>__<safe_name>.csv"""
        filename = self._safe_filename(base_name)
        prefixed = f"{self.username}__{filename}"
        return os.path.join("data", prefixed)

    def export_playlist_to_csv(
        self,
        playlist_name: str,
        filename: Optional[str] = None,
        fetch_features: bool = True,
    ) -> bool:
        playlist = self.find_playlist_by_name(playlist_name)
        if not playlist:
            print(f"[{self.username}] Playlist '{playlist_name}' not found!")
            print("Available playlists:")
            print("  - Liked Songs")
            for p in self.get_user_playlists():
                print(f"  - {p['name']}")
            return False

        if playlist.get("id") == "LIKED_SONGS":
            print(f"[{self.username}] Found special collection: Liked Songs")
            print(f"[{self.username}] Fetching liked songs data...")
            tracks = self.get_liked_songs(fetch_features=fetch_features)
            playlist_name = "Liked Songs"
        else:
            total = playlist["tracks"]["total"]
            print(f"[{self.username}] Found playlist: {playlist['name']} ({total} tracks)")
            print(f"[{self.username}] Fetching track data...")
            tracks = self.get_playlist_tracks(playlist["id"], fetch_features=fetch_features)

        if not tracks:
            print(f"[{self.username}] No exportable tracks found.")
            return False

        os.makedirs("data", exist_ok=True)
        filepath = self._prefixed_path(filename or playlist_name)
        print(f"[{self.username}] Writing {len(tracks)} tracks to {filepath}...")

        fieldnames = [
            "track_name","artist_names","album_name","album_type","release_date",
            "duration_ms","duration_min_sec","popularity","explicit","track_number","disc_number",
            "spotify_id","spotify_url","preview_url","added_at","added_by",
            "danceability","energy","key","loudness","mode","speechiness",
            "acousticness","instrumentalness","liveness","valence","tempo","time_signature",
        ]

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(tracks)

        print(f"[{self.username}] Successfully exported playlist to {filepath}")
        return True

    def export_all_playlists(self, fetch_features: bool = True, include_liked_songs: bool = True) -> bool:
        playlists = self.get_user_playlists()
        total_count = len(playlists) + (1 if include_liked_songs else 0)
        if total_count == 0:
            print(f"[{self.username}] No playlists found!")
            return False

        print(f"[{self.username}] Found {total_count} playlists. Exporting all...")
        success_count = 0

        if include_liked_songs:
            print(f"\n[{self.username}] [1/{total_count}] Exporting 'Liked Songs'...")
            try:
                tracks = self.get_liked_songs(fetch_features=fetch_features)
                if tracks:
                    os.makedirs("data", exist_ok=True)
                    filepath = self._prefixed_path("Liked Songs")
                    print(f"[{self.username}]   Writing {len(tracks)} tracks to {filepath}...")
                    fieldnames = [
                        "track_name","artist_names","album_name","album_type","release_date",
                        "duration_ms","duration_min_sec","popularity","explicit","track_number","disc_number",
                        "spotify_id","spotify_url","preview_url","added_at","added_by",
                        "danceability","energy","key","loudness","mode","speechiness",
                        "acousticness","instrumentalness","liveness","valence","tempo","time_signature",
                    ]
                    with open(filepath, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(tracks)
                    print(f"[{self.username}]   Successfully exported Liked Songs to {filepath}")
                    success_count += 1
                else:
                    print(f"[{self.username}]   No liked songs found.")
            except Exception as e:
                print(f"[{self.username}]   Failed to export Liked Songs: {e}")

        offset = 2 if include_liked_songs else 1
        for i, playlist in enumerate(playlists, offset):
            print(f"\n[{self.username}] [{i}/{total_count}] Exporting '{playlist['name']}'...")
            try:
                tracks = self.get_playlist_tracks(playlist["id"], fetch_features=fetch_features)
                if not tracks:
                    print(f"[{self.username}]   No exportable tracks found.")
                    continue
                os.makedirs("data", exist_ok=True)
                filepath = self._prefixed_path(playlist["name"])
                print(f"[{self.username}]   Writing {len(tracks)} tracks to {filepath}...")

                fieldnames = [
                    "track_name","artist_names","album_name","album_type","release_date",
                    "duration_ms","duration_min_sec","popularity","explicit","track_number","disc_number",
                    "spotify_id","spotify_url","preview_url","added_at","added_by",
                    "danceability","energy","key","loudness","mode","speechiness",
                    "acousticness","instrumentalness","liveness","valence","tempo","time_signature",
                ]
                with open(filepath, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(tracks)

                print(f"[{self.username}]   Successfully exported playlist to {filepath}")
                success_count += 1
            except Exception as e:
                print(f"[{self.username}]   Failed to export playlist '{playlist['name']}': {e}")
                continue

        print(f"\n[{self.username}] Export completed! Successfully exported {success_count}/{total_count}.")
        return success_count > 0

    def merge_lists(self) -> bool:
        data_dir = "data"
        output_file = os.path.join(data_dir, "total_list.csv")
        if not os.path.exists(data_dir):
            print(f"[{self.username}] Data directory '{data_dir}' not found!")
            return False
        csv_files = [f for f in os.listdir(data_dir) if f.endswith('.csv') and f != "total_list.csv"]
        if not csv_files:
            print(f"[{self.username}] No CSV files found in the data directory!")
            return False
        print(f"[{self.username}] Found {len(csv_files)} CSV files to merge: {', '.join(csv_files)}")

        unique_tracks = {}
        fieldnames = None
        for csv_file in csv_files:
            filepath = os.path.join(data_dir, csv_file)
            print(f"[{self.username}] Processing {filepath}...")
            with open(filepath, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if fieldnames is None:
                    fieldnames = reader.fieldnames
                for row in reader:
                    key = (row["track_name"], row["artist_names"])
                    if key not in unique_tracks:
                        unique_tracks[key] = row
        if not unique_tracks:
            print(f"[{self.username}] No tracks found in CSV files!")
            return False
        sorted_tracks = sorted(unique_tracks.values(), key=lambda x: x["track_name"])
        if fieldnames is None:
            fieldnames = [
                "track_name","artist_names","album_name","album_type","release_date",
                "duration_ms","duration_min_sec","popularity","explicit","track_number","disc_number",
                "spotify_id","spotify_url","preview_url","added_at","added_by",
                "danceability","energy","key","loudness","mode","speechiness",
                "acousticness","instrumentalness","liveness","valence","tempo","time_signature",
            ]
        print(f"[{self.username}] Writing {len(sorted_tracks)} unique tracks to {output_file}...")
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted_tracks)
        print(f"[{self.username}] Successfully merged playlists into {output_file}")
        return True

    # ---------- retry wrapper ----------
    def _retry(
        self, func, max_retries: int = 5, swallow_statuses: Optional[set] = None
    ):
        swallow_statuses = swallow_statuses or set()
        attempt = 0
        while True:
            try:
                return func()
            except SpotifyException as e:
                status = getattr(e, "http_status", None)
                if status == 429:
                    attempt += 1
                    retry_after = 1.0
                    try:
                        retry_after = float(e.headers.get("Retry-After", "1"))
                    except Exception:
                        pass
                    time.sleep(retry_after)
                    continue
                if status in swallow_statuses:
                    return None
                if status in (500, 502, 503, 504) and attempt < max_retries:
                    attempt += 1
                    backoff_sleep(attempt)
                    continue
                raise
            except Exception:
                if attempt < max_retries:
                    attempt += 1
                    backoff_sleep(attempt)
                    continue
                raise

def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export Spotify playlists to CSV (including Liked Songs)."
    )
    p.add_argument("--client-id", required=False, help="Spotify app Client ID")
    p.add_argument("--client-secret", required=False, help="Spotify app Client Secret")
    p.add_argument("--redirect-uri", default=REDIRECT_URI_DEFAULT,
                   help=f"Redirect URI registered in your app (default: {REDIRECT_URI_DEFAULT})")
    p.add_argument("--playlist",
                   help="Name of the playlist to export. Use 'Liked Songs' for liked songs.")
    p.add_argument("--outfile", help="CSV output file (overrides default)")
    p.add_argument("--no-features", action="store_true", help="Skip audio features.")
    p.add_argument("--all", action="store_true", help="Export all playlists incl. Liked Songs.")
    p.add_argument("--merge", action="store_true", help="Merge all CSV files in /data.")
    p.add_argument("--liked", action="store_true", help="Export only Liked Songs.")
    p.add_argument("--no-liked", action="store_true", help="Exclude Liked Songs when exporting all.")
    p.add_argument("--reauth", action="store_true",
                   help="Force re-consent (opens Spotify login even if a cache exists).")
    p.add_argument("--allow-mismatch", action="store_true",
                   help="Proceed even if the authenticated Spotify user ID != label in --users.")
    p.add_argument(
        "--users",
        help="Comma-separated list of usernames to export for (e.g., 'bob,mariaploughwood'). "
             "Each user will authenticate once; files are prefixed with '<user>__'."
    )
    return p.parse_args(argv)

def print_last_5_chars(client_id, client_secret):
    if client_id:
        print(f"Using Client ID ending in: {client_id[-5:]}")
    else:
        print("Client ID: None")
    if client_secret:
        print(f"Using Client Secret ending in: {client_secret[-5:]}")
    else:
        print("Client Secret: None")

def run_for_user(args: argparse.Namespace, username: str, client_id: str, client_secret: str):
    exporter = SpotifyPlaylistExporter(client_id, client_secret, args.redirect_uri,
                                       username=username, reauth=args.reauth)

    # Check for user mismatch
    if (exporter.authenticated_user_id and username not in (exporter.authenticated_user_id, exporter.authenticated_display_name)) \
            and not args.allow_mismatch:
        print(f"[{username}] WARNING: You authenticated as '{exporter.authenticated_display_name}' "
              f"(id: {exporter.authenticated_user_id}), not as label '{username}'. "
              f"This is OK if '{username}' is just a label for user '{exporter.authenticated_display_name}'.")
        # Continue execution instead of returning, as the user might have intentionally used a different label
    
    # Print authenticated user information
    try:
        me = exporter.sp.current_user()
        if me:
            print(f"[{username}] Authenticated as: {me.get('display_name') or me.get('id')}")
        else:
            print(f"[{username}] Authentication failed or user info unavailable")
    except Exception as e:
        print(f"[{username}] Error retrieving user info: {e}")

    if args.merge:
        ok = exporter.merge_lists()
        if ok:
            print(f"[{username}] Merge completed successfully!")
        else:
            print(f"[{username}] Merge failed!")
            sys.exit(1)
        return

    if args.liked:
        ok = exporter.export_playlist_to_csv(
            playlist_name="Liked Songs",
            filename=args.outfile,  # will still be prefixed
            fetch_features=(not args.no_features),
        )
        if ok:
            print(f"[{username}] Export completed successfully!")
        return

    if args.all:
        ok = exporter.export_all_playlists(
            fetch_features=(not args.no_features),
            include_liked_songs=not args.no_liked,
        )
        if ok:
            print(f"[{username}] Export completed successfully!")
        return

    # single playlist mode
    playlist_name = args.playlist
    if not playlist_name:
        exporter.list_playlists()
        print()
        playlist_name = input(f"[{username}] Enter the playlist to export (or 'Liked Songs'): ").strip()

    ok = exporter.export_playlist_to_csv(
        playlist_name=playlist_name,
        filename=args.outfile,  # will be prefixed
        fetch_features=(not args.no_features),
    )
    if ok:
        print(f"[{username}] Export completed successfully!")

def main(argv: List[str]):
    args = parse_args(argv)

    client_id = args.client_id
    client_secret = args.client_secret
    if not client_id or not client_secret:
        file_client_id, file_client_secret = load_secrets()
        client_id = client_id or file_client_id
        client_secret = client_secret or file_client_secret

    print_last_5_chars(client_id, client_secret)

    if not client_id or not client_secret:
        print("Error: Spotify Client ID and Client Secret are required.")
        print("Provide them as flags or in .api_secrets.")
        sys.exit(1)

    # Determine target users
    users: List[str]
    if args.users:
        users = [u.strip() for u in args.users.split(",") if u.strip()]
        if not users:
            print("Error: --users provided but empty after parsing.")
            sys.exit(1)
    else:
        # single-user behavior (backward compatible); prefix will be 'me'
        users = ["me"]

    for username in users:
        print(f"\n=== Processing user: {username} ===")
        try:
            run_for_user(args, username, client_id, client_secret)
        except SpotifyException as e:
            print(f"[{username}] Spotify API error ({getattr(e, 'http_status', '?')}): {e}")
        except Exception as e:
            print(f"[{username}] Unexpected error: {e}")

if __name__ == "__main__":
    main(sys.argv[1:])
