import subprocess
import logging

# Configure logging for debugging and tracing
logger = logging.getLogger("friday.applescript")

def run_applescript(script: str) -> tuple[bool, str, str]:
    """Executes a string of AppleScript code using macOS's native `osascript` compiler.

    This function communicates with osascript via standard input (stdin) to prevent
    command-line escaping issues and avoid command size limits.

    Args:
        script (str): The complete AppleScript code block to execute.

    Returns:
        tuple[bool, str, str]: A tuple containing:
            - success (bool): True if the command ran with exit code 0, False otherwise.
            - stdout (str): Stripped standard output from the execution.
            - stderr (str): Stripped standard error or exception message.
    """
    try:
        logger.debug(f"Executing AppleScript:\n{script}")
        # Run osascript, sending the script via stdin
        result = subprocess.run(
            ["osascript"],
            input=script,
            text=True,
            capture_output=True,
            check=False
        )
        
        success = (result.returncode == 0)
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        
        if not success:
            logger.warning(f"AppleScript execution failed (code {result.returncode}): {stderr}")
        else:
            logger.debug(f"AppleScript execution succeeded. Output: {stdout}")
            
        return success, stdout, stderr

    except FileNotFoundError:
        # Should only happen if not running on macOS or if path is somehow broken
        error_msg = "osascript utility not found. Ensure you are running on macOS."
        logger.error(error_msg)
        return False, "", error_msg
    except Exception as e:
        error_msg = f"Unexpected exception running AppleScript: {str(e)}"
        logger.exception(error_msg)
        return False, "", error_msg
