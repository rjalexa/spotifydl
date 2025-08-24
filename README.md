## Setup Instructions:

1. **Install uv (if not already installed):**
   ```bash
   # On macOS/Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh
   
   # On Windows
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. **Create a new project and install dependencies:**
   ```bash
   # Initialize a new project
   uv init spotify-exporter
   cd spotify-exporter
   
   # Add the spotipy dependency
   uv add spotipy
   ```

3. **Create a Spotify App:**
   - Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
   - Click "Create App"
   - Fill in app name and description
   - Set Redirect URI to: `http://127.0.0.1:8080/callback`
   - Copy your Client ID and Client Secret

4. **Set up API credentials:**
   - Copy the `.api_secrets_example` file to `.api_secrets`:
     ```bash
     cp .api_secrets_example .api_secrets
     ```
   - Edit `.api_secrets` and replace the placeholder values with your actual Client ID and Client Secret

5. **Update the script:**
   - Save the Python code as `spoti_lists.py` in your project directory

## Usage:

### Command Line Options:

```bash
# Run the script and it will list your playlists
uv run spoti_lists.py

# Export a specific playlist
uv run spoti_lists.py --playlist "My Awesome Playlist"

# Export only your Liked Songs
uv run spoti_lists.py --liked

# Export all playlists INCLUDING Liked Songs
uv run spoti_lists.py --all

# You can also provide client ID and secret as arguments (optional if in .api_secrets)
uv run spoti_lists.py --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET

# Skip audio features (faster export with fewer API calls)
uv run spoti_lists.py --playlist "My Playlist" --no-features

# Merge all CSV files in /data directory
uv run spoti_lists.py --merge
```

### Using Makefile:

The project includes a Makefile for easier usage:

```bash
# List all available playlists
make list_playlists

# Download all playlists including Liked Songs and merge into total_list.csv
make download_all

# Download all playlists including Liked Songs
make download_lists

# Download only Liked Songs
make download_liked

# Download a specific playlist
make download_playlist PLAYLIST="My Awesome Playlist"

# Merge all CSV files in /data directory
make merge_lists

# Install dependencies
make install

# Clean generated files
make clean
```

## Troubleshooting:

### INVALID_CLIENT: Invalid redirect URI Error

If you encounter this error when running the script, it means the redirect URI configured in your Spotify app doesn't match what the script is using. To fix this:

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
2. Select your app
3. Click "Edit Settings"
4. In the "Redirect URIs" section, make sure `http://127.0.0.1:8080/callback` is listed
5. If it's not there, add it and click "Save"
6. Try running the script again

Note: The redirect URI must exactly match what's in the code (`http://127.0.0.1:8080/callback`). Using `localhost` instead of `127.0.0.1` or a different port will cause this error.

## Features:

The program exports comprehensive metadata including:
- **Basic Info:** Track name, artists, album, release date
- **Spotify Data:** Popularity, duration, track numbers, Spotify URLs
- **Audio Features:** Danceability, energy, tempo, key, etc.
- **Playlist Data:** When tracks were added, who added them

## First Run:

When you run it for the first time, it will:
1. Open your browser for Spotify authentication
2. Ask for permission to read your playlists
3. Redirect to localhost (you can close the browser tab after authentication)

The CSV files will be saved in the `data/` directory with all the track metadata, making it easy to analyze your music in Excel, Google Sheets, or any other tool!

## Output Format:

Each playlist (including Liked Songs) is exported as a separate CSV file in the `data/` directory:
- Playlist files are named after the playlist (e.g., `My Playlist.csv`)
- Liked Songs are exported as `Liked Songs.csv`
- Merged playlists are saved as `data/total_list.csv`

All CSV files include the following columns:
- Track information (name, artists, album, etc.)
- Spotify data (popularity, duration, URLs)
- Audio features (danceability, energy, tempo, etc.)
- Playlist-specific data (when added, who added)
