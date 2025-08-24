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


REDIRECT_URI_DEFAULT = "http://127.0.0.1:8080/callback"  # loopback HTTP is allowed
# Added user-library-read scope for Liked Songs access
SCOPE = "playlist-read-private playlist-read-collaborative user-library-read"


def load_secrets():
    """Load Spotify API credentials from .api_secrets file."""
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
                    # Strip whitespace and quotes from value
                    value = value.strip().strip("\"'")
                    if key == "SPOTIFY_CLIENT_ID" and value:
                        client_id = value
                    elif key == "SPOTIFY_CLIENT_SECRET" and value:
                        client_secret = value

    # Check if we have both credentials and they're not empty
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
    ):
        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=SCOPE,
            )
        )

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
        
        # Get count of liked songs
        liked_songs_info = self._retry(lambda: self.sp.current_user_saved_tracks(limit=1))
        liked_songs_count = liked_songs_info.get('total', 0) if liked_songs_info else 0
        
        print(f"Found {len(playlists) + 1} playlists:")
        print(f" 1. Liked Songs ({liked_songs_count} tracks) [Special Collection]")
        
        for i, p in enumerate(playlists, 2):
            print(f"{i:2d}. {p['name']} ({p['tracks']['total']} tracks)")
        return playlists

    def find_playlist_by_name(self, playlist_name: str) -> Optional[dict]:
        # Special handling for "Liked Songs"
        if playlist_name.lower() in ["liked songs", "liked", "saved songs", "saved"]:
            # Return a special marker for liked songs
            return {"id": "LIKED_SONGS", "name": "Liked Songs", "tracks": {"total": -1}}
        
        for playlist in self.get_user_playlists():
            if playlist["name"].lower() == playlist_name.lower():
                return playlist
        return None

    # ---------- Liked Songs support ----------
    def get_liked_songs(self, fetch_features: bool = True) -> List[dict]:
        """Fetch all liked/saved songs from the user's library."""
        tracks: List[dict] = []
        raw_items: List[dict] = []
        
        print("Fetching liked songs...")
        
        # 1) Gather all liked songs
        results = self._retry(lambda: self.sp.current_user_saved_tracks(limit=50))
        total = results.get('total', 0) if results else 0
        print(f"Total liked songs: {total}")
        
        while results:
            raw_items.extend(results["items"])
            print(f"  Fetched {len(raw_items)}/{total} songs...")
            if results.get("next"):
                results = self._retry(lambda: self.sp.next(results))
            else:
                break
        
        # 2) Filter to valid track items and collect IDs
        valid_ids: List[str] = []
        for item in raw_items:
            tr = item.get("track")
            if not tr:
                continue
            if tr.get("is_local"):
                continue
            if not tr.get("id"):
                continue
            valid_ids.append(tr["id"])
        
        # 3) Batch-fetch audio features if requested
        features_by_id: Dict[str, Optional[dict]] = {}
        if fetch_features and valid_ids:
            print(f"Fetching audio features for {len(valid_ids)} tracks...")
            for i in range(0, len(valid_ids), 100):
                batch = valid_ids[i : i + 100]
                
                def _get_feats():
                    return self.sp.audio_features(batch)
                
                feats_list = self._retry(_get_feats, swallow_statuses={403})
                for tid, feats in zip(batch, feats_list or [None] * len(batch)):
                    features_by_id[tid] = feats
        
        # 4) Build final rows
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
                "added_by": "me",  # Liked songs are always added by the user
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

        # 1) Gather all items
        results = self._retry(lambda: self.sp.playlist_tracks(playlist_id))
        while results:
            raw_items.extend(results["items"])
            if results.get("next"):
                results = self._retry(lambda: self.sp.next(results))
            else:
                break

        # 2) Filter to valid track items; assemble base track rows
        valid_ids: List[str] = []
        for item in raw_items:
            tr = item.get("track")
            if not tr:
                continue  # removed/unavailable
            if tr.get("is_local"):
                continue  # local files have no audio features
            if tr.get("type") != "track":
                continue  # episodes/ads won't have audio features
            if not tr.get("id"):
                continue  # missing ID
            valid_ids.append(tr["id"])

        # 3) Batch-fetch audio features if requested
        features_by_id: Dict[str, Optional[dict]] = {}
        if fetch_features and valid_ids:
            for i in range(0, len(valid_ids), 100):
                batch = valid_ids[i : i + 100]

                # resilient fetch with retry handling
                def _get_feats():
                    return self.sp.audio_features(batch)

                feats_list = self._retry(
                    _get_feats, swallow_statuses={403}
                )  # 403 -> forbidden for some IDs
                # Spotipy returns list aligned to input with None for unknowns
                for tid, feats in zip(batch, feats_list or [None] * len(batch)):
                    features_by_id[tid] = feats

        # 4) Build final rows
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
                # Keep columns present but empty if features unavailable
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

    def export_playlist_to_csv(
        self,
        playlist_name: str,
        filename: Optional[str] = None,
        fetch_features: bool = True,
    ) -> bool:
        playlist = self.find_playlist_by_name(playlist_name)
        if not playlist:
            print(f"Playlist '{playlist_name}' not found!")
            print("Available playlists:")
            print("  - Liked Songs")
            for p in self.get_user_playlists():
                print(f"  - {p['name']}")
            return False

        # Check if this is the special "Liked Songs" playlist
        if playlist.get("id") == "LIKED_SONGS":
            print("Found special collection: Liked Songs")
            print("Fetching liked songs data...")
            tracks = self.get_liked_songs(fetch_features=fetch_features)
            playlist_name = "Liked Songs"
        else:
            total = playlist["tracks"]["total"]
            print(f"Found playlist: {playlist['name']} ({total} tracks)")
            print("Fetching track data...")
            tracks = self.get_playlist_tracks(playlist["id"], fetch_features=fetch_features)
        
        if not tracks:
            print("No exportable tracks found.")
            return False

        filename = filename or self._safe_filename(playlist_name)
        # Save to /data directory
        filepath = os.path.join("data", filename)
        print(f"Writing {len(tracks)} tracks to {filepath}...")

        fieldnames = [
            "track_name",
            "artist_names",
            "album_name",
            "album_type",
            "release_date",
            "duration_ms",
            "duration_min_sec",
            "popularity",
            "explicit",
            "track_number",
            "disc_number",
            "spotify_id",
            "spotify_url",
            "preview_url",
            "added_at",
            "added_by",
            "danceability",
            "energy",
            "key",
            "loudness",
            "mode",
            "speechiness",
            "acousticness",
            "instrumentalness",
            "liveness",
            "valence",
            "tempo",
            "time_signature",
        ]

        # Ensure the data directory exists
        os.makedirs("data", exist_ok=True)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(tracks)

        print(f"Successfully exported playlist to {filepath}")
        return True

    def export_all_playlists(self, fetch_features: bool = True, include_liked_songs: bool = True) -> bool:
        """Export all playlists to CSV files in the /data directory."""
        playlists = self.get_user_playlists()
        
        # Optionally add Liked Songs to the export list
        total_count = len(playlists)
        if include_liked_songs:
            total_count += 1
        
        if total_count == 0:
            print("No playlists found!")
            return False

        print(f"Found {total_count} playlists. Exporting all...")
        success_count = 0
        
        # Export Liked Songs first if requested
        if include_liked_songs:
            print(f"\n[1/{total_count}] Exporting 'Liked Songs'...")
            try:
                tracks = self.get_liked_songs(fetch_features=fetch_features)
                if not tracks:
                    print("  No liked songs found.")
                else:
                    filename = self._safe_filename("Liked Songs")
                    filepath = os.path.join("data", filename)
                    print(f"  Writing {len(tracks)} tracks to {filepath}...")
                    
                    fieldnames = [
                        "track_name",
                        "artist_names",
                        "album_name",
                        "album_type",
                        "release_date",
                        "duration_ms",
                        "duration_min_sec",
                        "popularity",
                        "explicit",
                        "track_number",
                        "disc_number",
                        "spotify_id",
                        "spotify_url",
                        "preview_url",
                        "added_at",
                        "added_by",
                        "danceability",
                        "energy",
                        "key",
                        "loudness",
                        "mode",
                        "speechiness",
                        "acousticness",
                        "instrumentalness",
                        "liveness",
                        "valence",
                        "tempo",
                        "time_signature",
                    ]
                    
                    os.makedirs("data", exist_ok=True)
                    
                    with open(filepath, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(tracks)
                    
                    print(f"  Successfully exported Liked Songs to {filepath}")
                    success_count += 1
            except Exception as e:
                print(f"  Failed to export Liked Songs: {e}")

        # Export regular playlists
        offset = 2 if include_liked_songs else 1
        for i, playlist in enumerate(playlists, offset):
            print(f"\n[{i}/{total_count}] Exporting '{playlist['name']}'...")
            try:
                # Use the playlist name as the filename
                filename = self._safe_filename(playlist["name"])
                tracks = self.get_playlist_tracks(
                    playlist["id"], fetch_features=fetch_features
                )
                if not tracks:
                    print("  No exportable tracks found.")
                    continue

                filepath = os.path.join("data", filename)
                print(f"  Writing {len(tracks)} tracks to {filepath}...")

                fieldnames = [
                    "track_name",
                    "artist_names",
                    "album_name",
                    "album_type",
                    "release_date",
                    "duration_ms",
                    "duration_min_sec",
                    "popularity",
                    "explicit",
                    "track_number",
                    "disc_number",
                    "spotify_id",
                    "spotify_url",
                    "preview_url",
                    "added_at",
                    "added_by",
                    "danceability",
                    "energy",
                    "key",
                    "loudness",
                    "mode",
                    "speechiness",
                    "acousticness",
                    "instrumentalness",
                    "liveness",
                    "valence",
                    "tempo",
                    "time_signature",
                ]

                # Ensure the data directory exists
                os.makedirs("data", exist_ok=True)

                with open(filepath, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(tracks)

                print(f"  Successfully exported playlist to {filepath}")
                success_count += 1
            except Exception as e:
                print(f"  Failed to export playlist '{playlist['name']}': {e}")
                continue

        print(
            f"\nExport completed! Successfully exported {success_count}/{total_count} playlists."
        )
        return success_count > 0

    def merge_lists(self) -> bool:
        """Merge all CSV files in the /data directory, deduplicate, and sort by track_name."""
        data_dir = "data"
        output_file = os.path.join(data_dir, "total_list.csv")
        
        # Check if data directory exists
        if not os.path.exists(data_dir):
            print(f"Data directory '{data_dir}' not found!")
            return False
        
        # Find all CSV files in the data directory
        csv_files = [f for f in os.listdir(data_dir) if f.endswith('.csv') and f != "total_list.csv"]
        if not csv_files:
            print("No CSV files found in the data directory!")
            return False
        
        print(f"Found {len(csv_files)} CSV files to merge: {', '.join(csv_files)}")
        
        # Read all CSV files and collect unique tracks
        unique_tracks = {}
        fieldnames = None
        
        for csv_file in csv_files:
            filepath = os.path.join(data_dir, csv_file)
            print(f"Processing {filepath}...")
            
            with open(filepath, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                
                # Store fieldnames from the first file
                if fieldnames is None:
                    fieldnames = reader.fieldnames
                
                # Process each row
                for row in reader:
                    # Create a unique key based on track_name and artist_names
                    key = (row["track_name"], row["artist_names"])
                    
                    # Only add if this track isn't already in our collection
                    if key not in unique_tracks:
                        unique_tracks[key] = row
        
        if not unique_tracks:
            print("No tracks found in CSV files!")
            return False
        
        # Convert to list and sort by track_name
        sorted_tracks = sorted(unique_tracks.values(), key=lambda x: x["track_name"])
        
        # Define fieldnames if not already defined (shouldn't happen but just in case)
        if fieldnames is None:
            fieldnames = [
                "track_name",
                "artist_names",
                "album_name",
                "album_type",
                "release_date",
                "duration_ms",
                "duration_min_sec",
                "popularity",
                "explicit",
                "track_number",
                "disc_number",
                "spotify_id",
                "spotify_url",
                "preview_url",
                "added_at",
                "added_by",
                "danceability",
                "energy",
                "key",
                "loudness",
                "mode",
                "speechiness",
                "acousticness",
                "instrumentalness",
                "liveness",
                "valence",
                "tempo",
                "time_signature",
            ]
        
        # Write to output file
        print(f"Writing {len(sorted_tracks)} unique tracks to {output_file}...")
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted_tracks)
        
        print(f"Successfully merged playlists into {output_file}")
        return True

    # ---------- retry wrapper ----------
    def _retry(
        self, func, max_retries: int = 5, swallow_statuses: Optional[set] = None
    ):
        """Retry Spotify requests on 429 / transient errors.
        If swallow_statuses is provided (e.g., {403}), return None on those status codes.
        """
        swallow_statuses = swallow_statuses or set()
        attempt = 0
        while True:
            try:
                return func()
            except SpotifyException as e:
                status = getattr(e, "http_status", None)
                # Rate limited
                if status == 429:
                    attempt += 1
                    retry_after = 1.0
                    try:
                        retry_after = float(e.headers.get("Retry-After", "1"))
                    except Exception:
                        pass
                    time.sleep(retry_after)
                    continue
                # Swallow configured statuses (e.g., 403 from audio-features batch)
                if status in swallow_statuses:
                    return None
                # Transient server errors
                if status in (500, 502, 503, 504) and attempt < max_retries:
                    attempt += 1
                    backoff_sleep(attempt)
                    continue
                # Propagate others
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
    p.add_argument(
        "--client-id",
        required=False,
        help="Spotify app Client ID (can also be set in .api_secrets file)",
    )
    p.add_argument(
        "--client-secret",
        required=False,
        help="Spotify app Client Secret (can also be set in .api_secrets file)",
    )
    p.add_argument(
        "--redirect-uri",
        default=REDIRECT_URI_DEFAULT,
        help=f"Redirect URI registered in your app (default: {REDIRECT_URI_DEFAULT})",
    )
    p.add_argument(
        "--playlist",
        help="Name of the playlist to export. Use 'Liked Songs' or 'Liked' for your liked songs. If omitted, lists playlists and prompts.",
    )
    p.add_argument("--outfile", help="CSV output file (defaults to '<playlist>.csv')")
    p.add_argument(
        "--no-features",
        action="store_true",
        help="Skip audio features (fewer API calls).",
    )
    p.add_argument("--all", action="store_true", help="Export all playlists including Liked Songs.")
    p.add_argument("--merge", action="store_true", help="Merge all CSV files in /data directory.")
    p.add_argument(
        "--liked",
        action="store_true",
        help="Export only Liked Songs.",
    )
    p.add_argument(
        "--no-liked",
        action="store_true",
        help="Exclude Liked Songs when exporting all playlists.",
    )
    return p.parse_args(argv)


def main(argv: List[str]):
    args = parse_args(argv)

    # Load secrets from .api_secrets file if not provided as arguments
    client_id = args.client_id
    client_secret = args.client_secret

    if not client_id or not client_secret:
        file_client_id, file_client_secret = load_secrets()
        if not client_id:
            client_id = file_client_id
        if not client_secret:
            client_secret = file_client_secret

    # Check if we have all required credentials
    if not client_id or not client_secret:
        print("Error: Spotify Client ID and Client Secret are required.")
        print(
            "Please provide them either as command-line arguments or in a .api_secrets file."
        )
        print("Make sure the credentials are not empty in the .api_secrets file.")
        sys.exit(1)

    exporter = SpotifyPlaylistExporter(client_id, client_secret, args.redirect_uri)

    if args.merge:
        # Merge all CSV files
        try:
            ok = exporter.merge_lists()
            if ok:
                print("Merge completed successfully!")
            else:
                print("Merge failed!")
                sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}")
            sys.exit(1)
    elif args.liked:
        # Export only Liked Songs
        try:
            ok = exporter.export_playlist_to_csv(
                playlist_name="Liked Songs",
                filename=args.outfile,
                fetch_features=(not args.no_features),
            )
            if ok:
                print("Export completed successfully!")
        except SpotifyException as e:
            print(f"Spotify API error ({getattr(e, 'http_status', '?')}): {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}")
            sys.exit(1)
    elif args.all:
        # Export all playlists, optionally including Liked Songs
        try:
            ok = exporter.export_all_playlists(
                fetch_features=(not args.no_features),
                include_liked_songs=not args.no_liked
            )
            if ok:
                print("Export completed successfully!")
        except SpotifyException as e:
            print(f"Spotify API error ({getattr(e, 'http_status', '?')}): {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}")
            sys.exit(1)
    else:
        playlist_name = args.playlist
        if not playlist_name:
            exporter.list_playlists()
            print()
            playlist_name = input("Enter the name of the playlist to export (or 'Liked Songs' for liked songs): ").strip()

        try:
            ok = exporter.export_playlist_to_csv(
                playlist_name=playlist_name,
                filename=args.outfile,
                fetch_features=(not args.no_features),
            )
            if ok:
                print("Export completed successfully!")
        except SpotifyException as e:
            print(f"Spotify API error ({getattr(e, 'http_status', '?')}): {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])