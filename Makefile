# Makefile for Spotify Playlist Downloader

# Default target
.PHONY: help
help:
	@echo "Spotify Playlist Downloader Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  download_all      - Download all playlists including Liked Songs and merge into total_list.csv"
	@echo "  download_lists    - Download all playlists including Liked Songs"
	@echo "  download_playlists_only - Download all playlists excluding Liked Songs"
	@echo "  download_liked    - Download only Liked Songs"
	@echo "  download_playlist - Download a specific playlist (use PLAYLIST=name)"
	@echo "  merge_lists       - Merge all CSV files in /data directory"
	@echo "  install          - Install dependencies"
	@echo "  clean            - Clean generated files"
	@echo "  list_playlists   - Show all playlists"
	@echo "  help             - Show this help message"
	@echo ""
	@echo "Examples:"
	@echo "  make download_all"
	@echo "  make download_lists"
	@echo "  make download_liked"
	@echo "  make download_playlist PLAYLIST='My Favorite Songs'"

# Download all playlists including Liked Songs and merge into total_list.csv
.PHONY: download_all
download_all:
	@echo "Downloading all playlists including Liked Songs..."
	python spoti_lists.py --all --no-features
	@echo "Merging all CSV files into total_list.csv..."
	python spoti_lists.py --merge

# Download all playlists including Liked Songs
.PHONY: download_lists
download_lists:
	@echo "Downloading all playlists including Liked Songs..."
	python spoti_lists.py --all --no-features

# Download all playlists excluding Liked Songs
.PHONY: download_playlists_only
download_playlists_only:
	@echo "Downloading all playlists excluding Liked Songs..."
	python spoti_lists.py --all --no-liked --no-features

# Download only Liked Songs
.PHONY: download_liked
download_liked:
	@echo "Downloading only Liked Songs..."
	python spoti_lists.py --liked --no-features

# Download a specific playlist
# Usage: make download_playlist PLAYLIST="Playlist Name"
.PHONY: download_playlist
download_playlist:
	@if [ -z "$(PLAYLIST)" ]; then \
		echo "Error: PLAYLIST variable not set"; \
		echo "Usage: make download_playlist PLAYLIST='Playlist Name'"; \
		exit 1; \
	fi
	@echo "Downloading playlist: $(PLAYLIST)"
	python spoti_lists.py --playlist "$(PLAYLIST)"

# Install dependencies
.PHONY: install
install:
	@echo "Installing dependencies..."
	uv sync

# Clean generated files
.PHONY: clean
clean:
	@echo "Cleaning generated files..."
	rm -rf data/
	find . -name "*.csv" -type f -delete

# Show all playlists
.PHONY: list_playlists
list_playlists:
	@echo "Listing available playlists..."
	python spoti_lists.py

# Merge all CSV files in /data directory
.PHONY: merge_lists
merge_lists:
	@echo "Merging all CSV files in /data directory..."
	python spoti_lists.py --merge