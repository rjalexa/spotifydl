# Makefile for Spotify Playlist Downloader

# Default target
.PHONY: help
help:
	@echo "Spotify Playlist Downloader Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  download_lists    - Download all playlists"
	@echo "  download_playlist - Download a specific playlist (use PLAYLIST=name)"
	@echo "  merge_lists       - Merge all CSV files in /data directory"
	@echo "  install          - Install dependencies"
	@echo "  clean            - Clean generated files"
	@echo "  help             - Show this help message"
	@echo ""
	@echo "Examples:"
	@echo "  make download_lists"
	@echo "  make download_playlist PLAYLIST='My Favorite Songs'"

# Download all playlists
.PHONY: download_lists
download_lists:
	@echo "Downloading all playlists..."
	python spoti_lists_dl.py --all --no-features

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
	python spoti_lists_dl.py --playlist "$(PLAYLIST)"

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
	python spoti_lists_dl.py

# Merge all CSV files in /data directory
.PHONY: merge_lists
merge_lists:
	@echo "Merging all CSV files in /data directory..."
	python spoti_lists_dl.py --merge