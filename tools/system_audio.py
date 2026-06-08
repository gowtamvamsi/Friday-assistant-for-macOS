from tools.registry import register_tool
from utils.applescript_runner import run_applescript

@register_tool
def set_volume(level: int) -> dict:
    """Changes the system audio output volume level.

    Args:
        level (int): The target volume percentage (0 to 100).

    Returns:
        dict: A status dictionary containing "status" (success/error) and a "message".
    """
    # Safeguard and clamp input to valid range (0-100)
    try:
        # Convert to string, strip '%', and parse as float then int, to handle inputs like "50%", "50", or 50.0
        parsed_level = int(float(str(level).replace('%', '').strip()))
    except ValueError:
        return {
            "status": "error",
            "message": f"Failed to set volume. Invalid level format: '{level}'"
        }
    
    clamped_level = max(0, min(100, parsed_level))
    # Check if the active audio device supports volume control (e.g. HDMI TVs return "missing value")
    check_script = "output volume of (get volume settings)"
    check_success, check_stdout, _ = run_applescript(check_script)
    if check_success and "missing value" in check_stdout:
        return {
            "status": "error",
            "message": "Volume control is not supported on the active audio device (e.g., HDMI/DisplayPort monitors). Please change the volume using your external device's physical remote."
        }

    script = f"set volume output volume {clamped_level}"
    success, stdout, stderr = run_applescript(script)
    
    if success:
        return {
            "status": "success",
            "message": f"System volume set to {clamped_level}%."
        }
    else:
        return {
            "status": "error",
            "message": f"Failed to set volume to {clamped_level}%. Error: {stderr}"
        }

@register_tool
def mute_volume() -> dict:
    """Mutes the macOS system audio output.

    Returns:
        dict: A status dictionary containing "status" (success/error) and a "message".
    """
    script = "set volume with output muted"
    success, stdout, stderr = run_applescript(script)
    
    if success:
        return {
            "status": "success",
            "message": "System audio output muted."
        }
    else:
        return {
            "status": "error",
            "message": f"Failed to mute system audio. Error: {stderr}"
        }

@register_tool
def unmute_volume() -> dict:
    """Unmutes the macOS system audio output.

    Returns:
        dict: A status dictionary containing "status" (success/error) and a "message".
    """
    script = "set volume without output muted"
    success, stdout, stderr = run_applescript(script)
    
    if success:
        return {
            "status": "success",
            "message": "System audio output unmuted."
        }
    else:
        return {
            "status": "error",
            "message": f"Failed to unmute system audio. Error: {stderr}"
        }

@register_tool
def get_volume_status() -> dict:
    """Queries the current volume level and mute state of the system.

    Returns:
        dict: A status dictionary containing "status", a "message", and "data"
              with "volume" (int or None, 0-100) and "muted" (bool or None).
    """
    # Return volume and muted status on separate lines to facilitate robust parsing
    script = """
    set volSettings to get volume settings
    set vol to output volume of volSettings
    set mut to output muted of volSettings
    return (vol as string) & "\\n" & (mut as string)
    """
    
    success, stdout, stderr = run_applescript(script)
    
    if success:
        try:
            parts = stdout.splitlines()
            if len(parts) >= 2:
                vol_str = parts[0].strip()
                mut_str = parts[1].strip()
                
                volume = None if vol_str == "missing value" else int(vol_str)
                muted = None if mut_str == "missing value" else (mut_str.lower() == "true")
                
                state_str = "unknown"
                if muted is True:
                    state_str = "muted"
                elif muted is False:
                    state_str = "active"
                    
                vol_display = f"{volume}%" if volume is not None else "unavailable"
                
                return {
                    "status": "success",
                    "message": f"System volume is {vol_display} (state: {state_str}).",
                    "data": {
                        "volume": volume,
                        "muted": muted
                    }
                }
        except (ValueError, IndexError) as e:
            return {
                "status": "error",
                "message": f"Failed to parse volume status. Raw output: {stdout}. Error: {str(e)}"
            }
            
    return {
        "status": "error",
        "message": f"Failed to query system volume settings. Error: {stderr}"
    }


