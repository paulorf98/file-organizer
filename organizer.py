"""
Advanced File Organizer
Description: Scans a target directory and organizes files into category
folders (Images, Documents, Code, ...) based on their extensions.

Features:
    * Configurable categories via an external JSON file
    * Command-line interface (argparse)
    * Dry-run mode (preview without moving anything)
    * Undo: every run is logged to a JSON history so it can be rolled back

Usage:
    python organizer.py --path ~/Downloads
    python organizer.py --path ~/Downloads --config my_rules.json
    python organizer.py --path ~/Downloads --dry-run
    python organizer.py --path ~/Downloads --undo
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# The history lives inside the organized folder, as a hidden file.
# Hidden files are skipped by the organizer, so it never moves its own log.
HISTORY_FILENAME = ".organizer_history.json"

# Used when the user does not provide a config file.
DEFAULT_CATEGORIES: Dict[str, List[str]] = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"],
    "Documents": [".pdf", ".docx", ".doc", ".txt", ".xlsx", ".csv", ".pptx"],
    "Code": [".py", ".rs", ".js", ".html", ".css", ".json", ".sh"],
    "Archives": [".zip", ".tar", ".gz", ".rar", ".7z"],
    "Audio": [".mp3", ".wav", ".flac", ".aac"],
}

# A move is stored as {"source": "<abs path>", "destination": "<abs path>"}
Move = Dict[str, str]


class ConfigError(ValueError):
    """Raised when the configuration file is missing or invalid."""


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
def _normalize_extension(extension: str) -> str:
    """Returns the extension lowercase and with a leading dot ('JPG' -> '.jpg')."""
    extension = extension.strip().lower()
    return extension if extension.startswith(".") else f".{extension}"


def load_categories(config_path: Path | str) -> Dict[str, List[str]]:
    """
    Loads and validates a JSON file with the format:

        {"Images": [".jpg", ".png"], "Books": [".epub", ".mobi"]}
    """
    path = Path(config_path)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in '{path}': {exc}") from exc

    if not isinstance(raw, dict) or not raw:
        raise ConfigError("Config must be a non-empty JSON object: {category: [extensions]}.")

    for category, extensions in raw.items():
        # Security: a category like "../../etc" would move files outside the target.
        if category in {".", ".."} or Path(category).name != category:
            raise ConfigError(f"Invalid category name: '{category}'.")
        if not isinstance(extensions, list) or not all(isinstance(e, str) for e in extensions):
            raise ConfigError(f"Category '{category}' must be a list of extension strings.")

    return raw


# --------------------------------------------------------------------------
# Core logic
# --------------------------------------------------------------------------
class FileOrganizer:
    """Handles scanning, relocation and rollback of files."""

    def __init__(
        self,
        target_directory: Path | str,
        categories: Optional[Dict[str, List[str]]] = None,
        dry_run: bool = False,
    ) -> None:
        self.target_dir = Path(target_directory).resolve()

        if not self.target_dir.is_dir():
            raise ValueError(f"The provided path '{target_directory}' is invalid or not a directory.")

        self.categories = categories if categories is not None else DEFAULT_CATEGORIES
        self.dry_run = dry_run

        # Reverse lookup {".jpg": "Images"} makes classification O(1).
        # reversed() so that, if an extension is in two categories, the first one wins.
        self._lookup: Dict[str, str] = {
            _normalize_extension(ext): category
            for category, extensions in reversed(list(self.categories.items()))
            for ext in extensions
        }

    @property
    def history_path(self) -> Path:
        return self.target_dir / HISTORY_FILENAME

    def _get_category(self, extension: str) -> str:
        """Determines the category folder name based on the file extension."""
        return self._lookup.get(extension.lower(), "Others")

    def organize(self) -> List[Move]:
        """Moves files into category folders and returns the list of moves made."""
        mode = " (dry run)" if self.dry_run else ""
        logger.info(f"Starting organization{mode} in: {self.target_dir}")

        moves: List[Move] = []

        for item in sorted(self.target_dir.iterdir()):
            if item.is_dir() or item.name.startswith(".") or not item.suffix:
                continue  # skip folders, hidden files (incl. our history) and no-extension files

            category_name = self._get_category(item.suffix)
            destination = self.target_dir / category_name / item.name

            if destination.exists():
                destination = self._resolve_collision(destination)

            if self.dry_run:
                logger.info(f"[DRY RUN] '{item.name}' -> '{category_name}/'")
                moves.append({"source": str(item), "destination": str(destination)})
                continue

            try:
                destination.parent.mkdir(exist_ok=True)
                shutil.move(str(item), str(destination))
            except OSError as exc:
                logger.error(f"Failed to move '{item.name}': {exc}")
                continue

            moves.append({"source": str(item), "destination": str(destination)})
            logger.info(f"Moved: '{item.name}' -> '{category_name}/'")

        if moves and not self.dry_run:
            self._append_history(moves)

        logger.info(f"Done. {len(moves)} file(s) {'would be ' if self.dry_run else ''}moved.")
        return moves

    def undo(self) -> int:
        """Reverts the most recent organize() run. Returns how many files were restored."""
        history = self._load_history()
        if not history:
            logger.warning("Nothing to undo: no history found.")
            return 0

        last_run = history.pop()
        restored = 0

        # Reverse order: undo the last move first.
        for move in reversed(last_run["moves"]):
            source, destination = Path(move["source"]), Path(move["destination"])

            if not destination.exists():
                logger.warning(f"Skipped: '{destination.name}' is no longer at '{destination.parent}'.")
                continue

            if source.exists():  # something new took the original name in the meantime
                source = self._resolve_collision(source)

            shutil.move(str(destination), str(source))
            restored += 1
            logger.info(f"Restored: '{destination.name}' -> '{source.parent.name}/'")

            try:
                destination.parent.rmdir()  # removes the category folder only if now empty
            except OSError:
                pass

        self._save_history(history)
        logger.info(f"Undo completed. {restored} file(s) restored.")
        return restored

    # ---- helpers ---------------------------------------------------------
    def _resolve_collision(self, destination: Path) -> Path:
        """Appends a numeric suffix if a file with the same name already exists."""
        stem, suffix = destination.stem, destination.suffix
        counter = 1

        while destination.exists():
            destination = destination.with_name(f"{stem}_{counter}{suffix}")
            counter += 1

        return destination

    def _load_history(self) -> List[dict]:
        if not self.history_path.exists():
            return []
        try:
            return json.loads(self.history_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"History file is corrupted: {self.history_path}") from exc

    def _save_history(self, history: List[dict]) -> None:
        if history:
            self.history_path.write_text(
                json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        else:
            self.history_path.unlink(missing_ok=True)  # nothing left to undo

    def _append_history(self, moves: List[Move]) -> None:
        history = self._load_history()
        history.append({"timestamp": datetime.now().isoformat(timespec="seconds"), "moves": moves})
        self._save_history(history)


# --------------------------------------------------------------------------
# Command-line interface
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Organize the files of a directory into category folders."
    )
    parser.add_argument("-p", "--path", required=True, help="Directory to organize.")
    parser.add_argument("-c", "--config", help="JSON file with custom category rules.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without moving files.")
    parser.add_argument("--undo", action="store_true", help="Revert the last organization run.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Returns a process exit code (0 = success, 1 = error)."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.undo and args.dry_run:
        parser.error("--undo and --dry-run cannot be used together.")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")

    try:
        categories = load_categories(args.config) if args.config else None
        organizer = FileOrganizer(args.path, categories=categories, dry_run=args.dry_run)

        if args.undo:
            organizer.undo()
        else:
            organizer.organize()
    except ValueError as error:  # also catches ConfigError
        logger.error(error)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
