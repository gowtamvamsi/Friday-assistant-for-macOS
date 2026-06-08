import os
import difflib
from tools.registry import register_tool
from utils.applescript_runner import run_applescript

def resolve_app_name(app_name: str, context: str = "open") -> str:
    """Resolves a user-provided application name using fuzzy matching and overrides.

    Args:
        app_name (str): The name provided by the user/LLM.
        context (str): "open" to query installed applications, or "close" to query running ones.

    Returns:
        str: The resolved application name, or the original name if no match is found.
    """
    app_lower = app_name.lower().strip()
    
    # 1. Explicit overrides for legacy systems, common aliases, or specific typos
    explicit_mappings = {
        "system preferences": "System Settings",
        "system preference": "System Settings",
        "preferences": "System Settings",
        "system prefs": "System Settings",
        "activity monior": "Activity Monitor",
        "activity preferences": "Activity Monitor",
        "monior": "Activity Monitor"
    }
    
    if app_lower in explicit_mappings:
        return explicit_mappings[app_lower]

    candidates = []
    if context == "close":
        # Query active GUI applications
        script = """
        tell application "System Events"
            set activeApps to name of every process whose background only is false
        end tell
        set AppleScript's text item delimiters to linefeed
        return activeApps as string
        """
        success, stdout, stderr = run_applescript(script)
        if success:
            candidates = [line.strip() for line in stdout.splitlines() if line.strip()]
    else:
        # Search common macOS directories for installed applications
        search_dirs = [
            "/Applications",
            "/System/Applications",
            "/Applications/Utilities",
            "/System/Applications/Utilities"
        ]
        for d in search_dirs:
            if os.path.exists(d):
                for item in os.listdir(d):
                    if item.endswith(".app"):
                        candidates.append(item[:-4]) # Strip ".app" extension

    if not candidates:
        return app_name

    candidates = list(set(candidates))

    # 2. Case-insensitive exact match check
    for cand in candidates:
        if cand.lower() == app_lower:
            return cand

    # 3. Substring match check (e.g. "Safari" inside "Safari Technology Preview" or vice versa)
    substring_matches = []
    for cand in candidates:
        if app_lower in cand.lower():
            substring_matches.append(cand)
            
    if substring_matches:
        # Sort by length difference to return the closest match
        substring_matches.sort(key=lambda x: len(x) - len(app_name))
        return substring_matches[0]

    # 4. Fuzzy match check using difflib
    close_matches = difflib.get_close_matches(app_name, candidates, n=1, cutoff=0.5)
    if close_matches:
        return close_matches[0]

    return app_name


@register_tool
def open_application(app_name: str) -> dict:
    """Launches or activates a specific macOS application.

    Args:
        app_name (str): The name of the application to open (e.g., "Safari", "Calculator").

    Returns:
        dict: A status dictionary containing "status" (success/error) and a "message".
    """
    import subprocess
    import logging
    logger = logging.getLogger("friday.system_apps")

    # Delegate to open_file if the app_name looks like a file path or a filename with an extension
    expanded = os.path.expanduser(app_name)
    if os.path.exists(expanded) or "/" in app_name or "\\" in app_name or ('.' in app_name and not app_name.endswith('.app')):
        logger.info(f"open_application: '{app_name}' looks like a file path, delegating to open_file.")
        from tools.file_ops import open_file
        return open_file(app_name)

    resolved_name = resolve_app_name(app_name, context="open")

    # Use `open -a` — the most reliable way to launch any macOS app.
    # Works whether the app is already running or not.
    result = subprocess.run(
        ["open", "-a", resolved_name],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        msg = f"Successfully opened and focused application '{resolved_name}'."
        if resolved_name != app_name:
            msg = f"Successfully opened and focused application '{resolved_name}' (resolved from '{app_name}')."
        logger.info(msg)
        return {"status": "success", "message": msg}

    # `open -a` failed (app not found) — try the raw user-provided name as fallback
    if resolved_name != app_name:
        fallback = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True,
            text=True
        )
        if fallback.returncode == 0:
            msg = f"Successfully opened application '{app_name}'."
            logger.info(msg)
            return {"status": "success", "message": msg}

    err = result.stderr.strip() or "Application not found."
    logger.warning(f"open_application failed for '{resolved_name}': {err}")
    return {
        "status": "error",
        "message": f"Could not open application '{app_name}'. {err}"
    }



@register_tool
def close_application(app_name: str) -> dict:
    """Closes/quits a specific macOS application if it is currently running.

    This tool checks the running processes list before attempting to quit the application.
    This prevents macOS from launching the application just to tell it to quit.

    Args:
        app_name (str): The name of the application to close (e.g., "Safari", "Calculator").

    Returns:
        dict: A status dictionary containing "status" (success/error) and a "message".
    """
    resolved_name = resolve_app_name(app_name, context="close")
    
    # Check if the process is running in System Events first.
    script = f"""
    try
        set targetApp to "{resolved_name}"
        tell application "System Events"
            set isRunning to (name of processes) contains targetApp
        end tell
        
        if isRunning then
            tell application targetApp to quit
            return "quit"
        else
            return "not_running"
        end if
    on error errMsg
        return "error: " & errMsg
    end try
    """
    
    success, stdout, stderr = run_applescript(script)
    
    if not success or stdout.startswith("error"):
        err_detail = stdout.replace("error: ", "") if stdout.startswith("error:") else stderr
        display_name = resolved_name if resolved_name == app_name else f"{resolved_name} (resolved from '{app_name}')"
        return {
            "status": "error",
            "message": f"Failed to check/close application '{display_name}'. Error: {err_detail}"
        }
        
    if stdout == "quit":
        msg = f"Successfully sent quit command to application '{resolved_name}'."
        if resolved_name != app_name:
            msg = f"Successfully sent quit command to application '{resolved_name}' (resolved from '{app_name}')."
            
        return {
            "status": "success",
            "message": msg
        }
    elif stdout == "not_running":
        display_name = resolved_name if resolved_name == app_name else f"{resolved_name} (resolved from '{app_name}')"
        return {
            "status": "success",
            "message": f"Application '{display_name}' is not currently running."
        }
        
    return {
        "status": "error",
        "message": f"Unexpected response from application close script: {stdout}"
    }

@register_tool
def list_running_applications() -> dict:
    """Lists all active running GUI applications on macOS.

    This tool filters out background helper services, menu bar items,
    and system daemons, returning only user-visible GUI applications.

    Returns:
        dict: A status dictionary containing "status", a "message", and "data"
              containing a "running_applications" list of strings.
    """
    script = """
    tell application "System Events"
        set activeApps to name of every process whose background only is false
    end tell
    set AppleScript's text item delimiters to linefeed
    return activeApps as string
    """
    
    success, stdout, stderr = run_applescript(script)
    
    if success:
        # Split output line-by-line and clean up names
        apps = [line.strip() for line in stdout.splitlines() if line.strip()]
        # Remove duplicates if any (System Events sometimes lists helper processes with identical names)
        apps = sorted(list(set(apps)))
        
        return {
            "status": "success",
            "message": f"Found {len(apps)} active GUI applications running.",
            "data": {
                "running_applications": apps
            }
        }
    else:
        return {
            "status": "error",
            "message": f"Failed to list running applications. Error: {stderr}"
        }
