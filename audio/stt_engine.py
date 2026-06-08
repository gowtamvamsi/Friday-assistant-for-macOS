import os
import logging
import torch
import whisper

logger = logging.getLogger("friday.stt_engine")

class STTEngine:
    """Manages local Speech-to-Text translation utilizing local OpenAI Whisper models."""

    def __init__(self, model_name: str | None = None):
        """Initializes the Speech-To-Text Engine.

        Args:
            model_name (str): The size of the Whisper model to load.
                              Defaults to WHISPER_MODEL env var or 'base'.
        """
        self.model_name = model_name or os.getenv("WHISPER_MODEL", "base")
        self.model = None
        
        # Check for Apple Silicon GPU acceleration (MPS) or CUDA
        if torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"
            
        logger.info(f"STTEngine initialized. Target execution device: '{self.device}'")

    def load_model(self):
        """Loads the Whisper model into memory.

        Lazy-loaded on first request to prevent blocking program initialization.
        """
        if self.model is None:
            logger.info(f"Loading local Whisper model '{self.model_name}' on device '{self.device}'...")
            # We explicitly pass the device. Note that on CPU, fp16 is disabled to avoid warnings.
            self.model = whisper.load_model(self.model_name, device=self.device)
            logger.info(f"Successfully loaded Whisper model '{self.model_name}'.")

    def transcribe(self, audio_file_path: str) -> str:
        """Transcribes a local WAV audio file to raw text.

        Args:
            audio_file_path (str): The absolute path to the WAV file.

        Returns:
            str: The transcribed text block.
        """
        if not os.path.exists(audio_file_path):
            logger.error(f"STT Error: Audio file does not exist: {audio_file_path}")
            return ""

        try:
            self.load_model()
            logger.info(f"Beginning local audio transcription for: {audio_file_path}")
            
            # Use an initial prompt to bias Whisper's spelling for our application context
            # (e.g. resolving 'Notes' instead of 'North', and 'System Settings' instead of other strings).
            prompt = "Hello Friday. Open Notes. Close Notes. System Settings. Safari. Volume. Mute. Unmute."
            
            # fp16=False is safer for standard CPUs and fully supported by MPS
            result = self.model.transcribe(
                audio_file_path, 
                fp16=(self.device != "cpu"),
                initial_prompt=prompt
            )
            text = result.get("text", "").strip()
            
            logger.info(f"Transcription completed successfully.")

            return text
        except Exception as e:
            logger.exception(f"Unexpected error transcribing audio: {str(e)}")
            return ""
