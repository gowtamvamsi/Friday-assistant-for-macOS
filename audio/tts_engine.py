import os
import logging
from typing import Generator
import numpy as np

logger = logging.getLogger("friday.tts_engine")

class TTSEngine:
    """Handles local Text-to-Speech synthesis using Kokoro-82M on Apple Silicon via MLX."""

    def __init__(self, model_name: str = "mlx-community/Kokoro-82M-bf16"):
        """Initializes the TTS Engine.

        Args:
            model_name (str): Hugging Face repo ID or local path for Kokoro MLX model weights.
        """
        self.model_name = model_name
        self.tts = None

    def load_model(self):
        """Lazy-loads the Kokoro MLX model weights into memory on the first request."""
        if self.tts is None:
            logger.info(f"Loading local Kokoro MLX model '{self.model_name}'...")
            try:
                from kokoro_mlx import KokoroTTS
                self.tts = KokoroTTS.from_pretrained(self.model_name)
                logger.info("Successfully loaded Kokoro MLX model.")
            except ImportError:
                logger.error("Failed to import 'kokoro_mlx'. Please check package installation.")
                raise
            except Exception as e:
                logger.exception(f"Unexpected error loading Kokoro model: {e}")
                raise

    def generate_stream(self, text: str, voice: str = "af_heart", speed: float = 1.0) -> Generator[np.ndarray, None, None]:
        """Synthesizes text into audio chunks in a streaming generator.

        Args:
            text (str): The text phrase to synthesize.
            voice (str): Voice preset ID (e.g. 'af_heart', 'am_adam', 'bf_emma').
            speed (float): Playback speed multiplier.

        Yields:
            np.ndarray: float32 audio samples of native 24000Hz PCM.
        """
        self.load_model()
        if not text.strip():
            return

        logger.debug(f"Synthesizing text: '{text}' (voice: '{voice}', speed: {speed})")
        try:
            # kokoro-mlx generate_stream yields chunks of float32 numpy arrays
            for chunk in self.tts.generate_stream(text, voice=voice, speed=speed):
                yield chunk
        except Exception as e:
            logger.error(f"Error during TTS synthesis: {e}")
