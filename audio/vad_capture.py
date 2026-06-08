import os
import time
import wave
import logging
import numpy as np
import sounddevice as sd

logger = logging.getLogger("friday.vad_capture")


class SpeechCapture:
    """Records audio from the default macOS microphone using dynamic calibration and energy VAD.

    Uses the `sounddevice` library (which ships its own PortAudio binary) for
    reliable cross-device audio capture on macOS, including Bluetooth devices.
    """

    def __init__(self, sample_rate: int = 16000, chunk_size: int = 512):
        """Initializes the Speech Capture helper.

        Args:
            sample_rate (int): Recording rate resampled to by CoreAudio (16000 Hz for Whisper).
            chunk_size (int): Frames per buffer chunk (512 frames ≈ 32ms at 16kHz).
        """
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.silence_threshold = None

    def _refresh_and_log_device(self):
        """Forces PortAudio to rescan the macOS CoreAudio routing table.
        This ensures we always target the *current* default input device (e.g., newly connected AirPods),
        rather than what was default when the Python app initially started."""
        try:
            # Terminate and reinitialize to clear the cached device list
            sd._terminate()
            sd._initialize()
            
            info = sd.query_devices(kind='input')
            logger.info(
                f"Targeting active macOS microphone: '{info['name']}' "
                f"(Native sample rate: {int(info['default_samplerate'])}Hz)"
            )
        except Exception as e:
            logger.warning(f"Could not query or refresh default input device: {e}")

    def calibrate(self, calibration_duration: float = 1.0):
        """Records ambient room noise to establish a baseline silence threshold."""
        logger.info("Calibrating background noise threshold. Please keep silent...")
        self._refresh_and_log_device()

        try:
            # Record a short sample of ambient audio
            num_frames = int(calibration_duration * self.sample_rate)
            audio = sd.rec(
                num_frames,
                samplerate=self.sample_rate,
                channels=1,
                dtype='int16',
                blocking=True
            )
        except Exception as e:
            logger.error(f"Failed to record for VAD calibration: {e}")
            self.silence_threshold = 300.0
            return

        audio_flat = audio.flatten()
        if len(audio_flat) == 0:
            self.silence_threshold = 300.0
            logger.warning(f"Empty calibration recording. Using default threshold: {self.silence_threshold}")
            return

        # Calculate ambient RMS over the whole calibration window
        ambient_rms = float(np.sqrt(np.mean(np.square(audio_flat.astype(np.float32)))))

        if ambient_rms == 0.0:
            logger.debug("Ambient RMS is exactly 0.0. This is normal for digital headsets (AirPods) with hardware noise gating.")

        # Set threshold to 1.8x the average ambient RMS noise floor.
        # Add a safety floor of 40.0 to prevent micro-fluctuations, but keep it low enough
        # for digital Bluetooth headsets (like AirPods) that have a noise floor of 0.0
        # and a lower overall voice gain.
        self.silence_threshold = max(ambient_rms * 1.8, 40.0)
        logger.info(
            f"Calibration complete. Ambient RMS: {ambient_rms:.2f}. "
            f"Dynamic silence threshold: {self.silence_threshold:.2f}"
        )

    def record_command(self, output_path: str, max_duration: float = 10.0, silence_duration_limit: float = 1.5, on_speech_start: object = None, on_mic_open: object = None) -> bool:
        """Captures microphone audio, stopping recording once silence is detected.

        Uses a streaming callback approach via sounddevice for low-latency chunk
        processing with VAD (Voice Activity Detection).

        Args:
            output_path (str): File system path to write the WAV file.
            max_duration (float): Maximum recording length in seconds.
            silence_duration_limit (float): Silence gap in seconds before cutoff.
            on_speech_start (callable): Optional callback triggered immediately when user speech is detected.
            on_mic_open (callable): Optional callback triggered immediately after the microphone stream is opened (e.g. for Bluetooth volume sync).

        Returns:
            bool: True if a voice command was successfully captured and saved, False if it timed out.
        """
        if self.silence_threshold is None:
            self.calibrate()

        self._refresh_and_log_device()

        frames = []
        speech_started = False
        silent_chunk_counter = 0

        # Calculate how many consecutive silent chunks correspond to the duration limit
        chunk_duration = self.chunk_size / self.sample_rate
        max_silent_chunks = max(int(silence_duration_limit / chunk_duration), 1)
        total_chunks = int(max_duration / chunk_duration)

        # User has 3 seconds to start speaking after wake word trigger
        speech_start_timeout_chunks = int(3.0 / chunk_duration)

        logger.info("Microphone is listening...")

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='int16',
                blocksize=self.chunk_size
            ) as stream:
                if on_mic_open:
                    try:
                        on_mic_open()
                    except Exception as e:
                        logger.error(f"Error in on_mic_open callback: {e}")

                for step in range(total_chunks):
                    data, overflowed = stream.read(self.chunk_size)
                    if overflowed:
                        logger.debug("Audio input overflow detected (non-fatal).")

                    audio_chunk = data.flatten()
                    frames.append(audio_chunk.tobytes())

                    # Calculate Root Mean Square energy
                    rms = float(np.sqrt(np.mean(np.square(audio_chunk.astype(np.float32)))))

                    if not speech_started:
                        if rms > self.silence_threshold:
                            speech_started = True
                            logger.info("Speech detected. Recording command...")
                            if on_speech_start:
                                try:
                                    on_speech_start()
                                except Exception as e:
                                    logger.error(f"Error executing on_speech_start callback: {e}")
                        elif step > speech_start_timeout_chunks:
                            logger.info("No speech detected within start timeout period. Aborting record.")
                            break
                    else:
                        # Speech is active; monitor for the silence cutoff gate
                        if rms < self.silence_threshold:
                            silent_chunk_counter += 1
                            if silent_chunk_counter >= max_silent_chunks:
                                logger.info(
                                    f"Silence detected continuously for "
                                    f"{silence_duration_limit * 1000:.0f}ms. Closing microphone."
                                )
                                break
                        else:
                            silent_chunk_counter = 0

        except Exception as e:
            logger.error(f"Audio capture error: {e}")
            return False

        if not speech_started or len(frames) == 0:
            return False

        # Save PCM frames to WAV file
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with wave.open(output_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit = 2 bytes
                wf.setframerate(self.sample_rate)
                wf.writeframes(b"".join(frames))
            return True
        except Exception as e:
            logger.error(f"Failed to write audio WAV file: {e}")
            return False

    def terminate(self):
        """Cleans up the SpeechCapture instance (no-op for sounddevice)."""
        pass
