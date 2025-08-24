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
   - Save the Python code as `spotify_exporter.py` in your project directory

## Usage:

```bash
# Run the script and it will list your playlists
uv run spotify_exporter.py

# Or specify a playlist name directly
uv run spotify_exporter.py --playlist "My Awesome Playlist"

# You can also provide client ID and secret as arguments (optional if in .api_secrets)
uv run spotify_exporter.py --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET
```

## Alternative: One-line setup with uv

If you prefer to set up everything in one go:

```bash
# Create project, add dependency, and run in one flow
uv init spotify-exporter && cd spotify-exporter && uv add spotipy
# Then save the script as spotify_exporter.py and set up your .api_secrets file
# Finally run:
uv run spotify_exporter.py
```

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

The CSV file will be saved with all the track metadata, making it easy to analyze your music in Excel, Google Sheets, or any other tool!
