import os
import logging
import numpy as np
import sounddevice as sd
import pvporcupine
from dotenv import load_dotenv

logger = logging.getLogger("friday.wake_word")

class WakeWordDetector:
    """Listens continuously in the background for a voice wake word using Picovoice Porcupine."""

    def __init__(self, api_key: str | None = None, keyword: str = "porcupine"):
        """Initializes the WakeWordDetector.

        Args:
            api_key (str | None): Picovoice API Key. If None, loaded from env.
            keyword (str): Target wake word (default: "porcupine").
        """
        load_dotenv()
        self.api_key = api_key or os.getenv("PICOVOICE_API_KEY")
        self.keyword = keyword
        self.porcupine = None

        if not self.api_key:
            logger.error("\n" + "=" * 60 +
                         f"\n🚨  PICOVOICE_API_KEY is missing in your .env file! \n"
                         f"Friday requires a Picovoice Access Key for wake-word detection.\n"
                         f"1. Sign up for a free developer account at: https://console.picovoice.ai/\n"
                         f"2. Copy your Access Key.\n"
                         f"3. Create a '.env' file in the project directory and add:\n"
                         f"   PICOVOICE_API_KEY=your_key_here\n" +
                         "=" * 60 + "\n")

    def init_porcupine(self):
        """Loads and initializes the Porcupine engine."""
        if self.porcupine is not None:
            return

        if not self.api_key:
            raise ValueError("Cannot initialize Porcupine: PICOVOICE_API_KEY is not set.")

        try:
            logger.info(f"Initializing Porcupine wake-word engine (keyword: '{self.keyword}')...")
            self.porcupine = pvporcupine.create(
                access_key=self.api_key,
                keywords=[self.keyword]
            )
            logger.info("Porcupine wake-word engine initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Porcupine. Details: {e}")
            raise

    def wait_for_wake_word(self) -> bool:
        """Blocks and listens continuously until the wake word is detected.

        Uses the `sounddevice` library for reliable cross-device audio capture
        on macOS, including Bluetooth devices like AirPods.

        Returns:
            bool: True if the wake word was successfully spotted, False if interrupted/failed.
        """
        self.init_porcupine()

        # Porcupine expects specific audio specs: 16kHz, 16-bit mono PCM
        sample_rate = self.porcupine.sample_rate
        frame_length = self.porcupine.frame_length

        try:
            info = sd.query_devices(kind='input')
            logger.info(
                f"Porcupine targeting default microphone: '{info['name']}' "
                f"(Native sample rate: {int(info['default_samplerate'])}Hz)"
            )
        except Exception as e:
            logger.warning(f"Could not query default input device: {e}")

        try:
            input_stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype='int16',
                blocksize=frame_length
            )
            input_stream.start()
        except Exception as e:
            logger.error(f"Failed to open audio input stream for wake word listener: {e}")
            return False

        logger.info(f"Friday is listening for the wake word '{self.keyword}'...")

        try:
            while True:
                # Read a single frame of audio
                data, overflowed = input_stream.read(frame_length)
                audio_frame = data.flatten()

                # Process the audio frame with Porcupine
                result = self.porcupine.process(audio_frame)

                if result >= 0:
                    logger.info(f"Wake word '{self.keyword}' detected!")
                    return True
        except KeyboardInterrupt:
            logger.info("Wake word listener interrupted by user.")
            return False
        except Exception as e:
            logger.error(f"Error in wake-word detection loop: {e}")
            return False
        finally:
            input_stream.stop()
            input_stream.close()

    def terminate(self):
        """Cleans up Porcupine structures."""
        if self.porcupine:
            self.porcupine.delete()
            self.porcupine = None
