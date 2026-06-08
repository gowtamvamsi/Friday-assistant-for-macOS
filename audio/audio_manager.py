import logging
from utils.applescript_runner import run_applescript

logger = logging.getLogger("friday.audio_manager")

class AudioManager:
    """Manages macOS system audio output levels, specifically for ducking during voice capture."""

    def __init__(self):
        self.target_volume = None

    def capture_a2dp_volume(self):
        """Captures the current macOS system volume (usually A2DP) before opening the microphone."""
        script = "output volume of (get volume settings)"
        success, stdout, _ = run_applescript(script)
        if success:
            val = stdout.strip()
            if val != "missing value":
                try:
                    self.target_volume = int(val)
                    logger.debug(f"Captured target volume: {self.target_volume}%")
                except ValueError:
                    pass

    def sync_hfp_volume(self):
        """Applies the captured volume to the current audio profile (usually HFP) to prevent jumps."""
        if self.target_volume is None:
            return

        # Give macOS a split second to finish the Bluetooth profile switch
        import time
        time.sleep(0.4)

        script = "output volume of (get volume settings)"
        success, stdout, _ = run_applescript(script)
        
        if success:
            val = stdout.strip()
            if val != "missing value":
                try:
                    current_vol = int(val)
                    if current_vol != self.target_volume:
                        logger.info(f"Syncing HFP profile volume ({current_vol}%) to match A2DP ({self.target_volume}%)...")
                        run_applescript(f"set volume output volume {self.target_volume}")
                except ValueError:
                    pass

