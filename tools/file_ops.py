"""
tools/file_ops.py — File System Tools for Friday

Provides smart file operations:
  - open_file: Open any file or folder with its default macOS app
  - find_recent_file: Find the most recently modified file in a directory
  - list_directory: List contents of a folder
"""

import os
import subprocess
import logging
from typing import Dict, Any
from tools.registry import register_tool

logger = logging.getLogger("friday.file_ops")

# Common user directory aliases
_DIR_ALIASES = {
    "downloads":  os.path.expanduser("~/Downloads"),
    "download":   os.path.expanduser("~/Downloads"),
    "desktop":    os.path.expanduser("~/Desktop"),
    "documents":  os.path.expanduser("~/Documents"),
    "document":   os.path.expanduser("~/Documents"),
    "pictures":   os.path.expanduser("~/Pictures"),
    "photos":     os.path.expanduser("~/Pictures"),
    "music":      os.path.expanduser("~/Music"),
    "movies":     os.path.expanduser("~/Movies"),
    "home":       os.path.expanduser("~"),
    "~":          os.path.expanduser("~"),
}


def _resolve_directory(path: str) -> str:
    """Resolves a directory alias or expands ~ in a path."""
    clean = path.strip().lower().rstrip("/")
    if clean in _DIR_ALIASES:
        return _DIR_ALIASES[clean]
    return os.path.expanduser(path)


@register_tool
def find_recent_file(directory: str = "Downloads", file_type: str = "") -> Dict[str, Any]:
    """
    Finds the most recently modified file in a directory and opens it.

    Works with natural language directory names like 'Downloads', 'Desktop', 'Documents'.
    Optionally filter by file type extension (e.g. 'pdf', 'png', 'zip').

    Args:
        directory (str): The directory to search in. Accepts 'Downloads', 'Desktop',
                         'Documents', 'Pictures', 'Music', 'Movies', or any absolute path.
        file_type (str): Optional file extension filter without dot (e.g. 'pdf', 'png').
                         Leave empty to find the most recent file of any type.

    Returns:
        dict: Status and message describing the file that was found and opened.
    """
    resolved_dir = _resolve_directory(directory)

    if not os.path.isdir(resolved_dir):
        return {
            "status": "error",
            "message": f"Directory '{directory}' not found at {resolved_dir}."
        }

    try:
        entries = []
        for name in os.listdir(resolved_dir):
            # Skip hidden files
            if name.startswith("."):
                continue
            full_path = os.path.join(resolved_dir, name)
            if not os.path.isfile(full_path):
                continue
            # Apply extension filter if provided
            if file_type:
                ext = file_type.lower().lstrip(".")
                if not name.lower().endswith(f".{ext}"):
                    continue
            entries.append((os.path.getmtime(full_path), full_path, name))

        if not entries:
            filter_msg = f" with extension '.{file_type}'" if file_type else ""
            return {
                "status": "error",
                "message": f"No files{filter_msg} found in {directory}."
            }

        # Sort by modification time, newest first
        entries.sort(reverse=True)
        _, most_recent_path, most_recent_name = entries[0]

        logger.info(f"find_recent_file: opening '{most_recent_name}' from {resolved_dir}")

        # Open with macOS default app
        result = subprocess.run(
            ["open", most_recent_path],
            capture_output=True, text=True
        )

        if result.returncode == 0:
            import datetime
            mtime = os.path.getmtime(most_recent_path)
            modified = datetime.datetime.fromtimestamp(mtime).strftime("%b %d at %I:%M %p")
            return {
                "status": "success",
                "message": f"Opened '{most_recent_name}' from {directory} (last modified {modified})."
            }
        else:
            return {
                "status": "error",
                "message": f"Found '{most_recent_name}' but could not open it: {result.stderr.strip()}"
            }

    except Exception as e:
        logger.exception("find_recent_file failed.")
        return {"status": "error", "message": f"Failed to find recent file: {e}"}


@register_tool
def open_file(file_path: str) -> Dict[str, Any]:
    """
    Opens a specific file or folder using its default macOS application.

    Supports absolute paths, paths with ~ (home directory), and relative paths
    from common locations like Downloads or Desktop.

    Args:
        file_path (str): Path to the file or folder to open.
                         Examples: '~/Downloads/report.pdf', '/Users/me/Desktop/photo.png'

    Returns:
        dict: Status and message.
    """
    expanded = os.path.expanduser(file_path)

    # If relative path, try resolving from common directories
    if not os.path.isabs(expanded):
        for base_dir in [
            os.path.expanduser("~/Downloads"),
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Documents"),
        ]:
            candidate = os.path.join(base_dir, expanded)
            if os.path.exists(candidate):
                expanded = candidate
                break

    if not os.path.exists(expanded):
        return {
            "status": "error",
            "message": f"File not found: '{file_path}'. Please check the path and try again."
        }

    logger.info(f"open_file: opening '{expanded}'")
    result = subprocess.run(["open", expanded], capture_output=True, text=True)

    if result.returncode == 0:
        name = os.path.basename(expanded)
        return {"status": "success", "message": f"Opened '{name}'."}
    else:
        return {
            "status": "error",
            "message": f"Could not open '{file_path}': {result.stderr.strip()}"
        }


@register_tool
def list_directory(directory: str = "Downloads") -> Dict[str, Any]:
    """
    Lists the most recent files in a directory, sorted by modification time (newest first).

    Args:
        directory (str): Directory to list. Accepts 'Downloads', 'Desktop', 'Documents',
                         'Pictures', or any absolute path.

    Returns:
        dict: Status, message, and list of file names with their sizes and dates.
    """
    resolved_dir = _resolve_directory(directory)

    if not os.path.isdir(resolved_dir):
        return {
            "status": "error",
            "message": f"Directory '{directory}' not found."
        }

    try:
        import datetime
        entries = []
        for name in os.listdir(resolved_dir):
            if name.startswith("."):
                continue
            full_path = os.path.join(resolved_dir, name)
            mtime = os.path.getmtime(full_path)
            size_bytes = os.path.getsize(full_path) if os.path.isfile(full_path) else 0
            is_dir = os.path.isdir(full_path)
            entries.append((mtime, name, size_bytes, is_dir))

        entries.sort(reverse=True)
        top = entries[:15]  # Return top 15 most recent

        file_list = []
        for mtime, name, size, is_dir in top:
            modified = datetime.datetime.fromtimestamp(mtime).strftime("%b %d")
            if is_dir:
                file_list.append(f"{name}/ (folder, {modified})")
            else:
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size/1024:.1f} KB"
                else:
                    size_str = f"{size/(1024*1024):.1f} MB"
                file_list.append(f"{name} ({size_str}, {modified})")

        summary = f"Found {len(entries)} items in {directory}. Most recent: " + ", ".join(
            n.split(" (")[0] for _, n, _, _ in top[:5]
        )

        return {
            "status": "success",
            "message": summary,
            "data": {"files": file_list, "directory": resolved_dir}
        }

    except Exception as e:
        logger.exception("list_directory failed.")
        return {"status": "error", "message": f"Failed to list directory: {e}"}
