import queue
import logging
import threading
from typing import Any
import numpy as np
import sounddevice as sd

logger = logging.getLogger("friday.audio_player")

class AudioPlayer:
    """Manages non-blocking, interruptible audio playback of PCM chunks at 24kHz.

    Utilizes sounddevice's OutputStream with a real-time PortAudio callback
    for ultra-low latency and instant interruption support.
    """

    def __init__(self, sample_rate: int = 24000):
        """Initializes the Audio Player.

        Args:
            sample_rate (int): Output playback rate (must match Kokoro's native 24000Hz).
        """
        self.sample_rate = sample_rate
        self.audio_queue = queue.Queue()
        self.stream = None
        self.playing = False
        self.device_sample_rate = self.sample_rate # Will be updated when stream starts
        
        # Synchronization
        self.interrupted = threading.Event()
        self.current_chunk = np.array([], dtype=np.float32)
        self.chunk_lock = threading.Lock()
        
        # Heartbeat to detect macOS Bluetooth stream stalls
        import time
        self.last_callback_time = time.time()

    def start(self):
        """Starts the background PortAudio OutputStream at the device's native sample rate."""
        if self.stream is not None:
            return

        self.interrupted.clear()
        import time
        self.last_callback_time = time.time()
        try:
            # We use samplerate=None to force sounddevice to use the native hardware sample rate.
            # This prevents macOS CoreAudio from renegotiating the format on Bluetooth headphones,
            # which is the root cause of the "system volume resets to 100%" bug.
            self.stream = sd.OutputStream(
                samplerate=None,
                channels=1,
                dtype='float32',
                callback=self._audio_callback
            )
            self.device_sample_rate = self.stream.samplerate
            self.stream.start()
            self.playing = True
            logger.info(f"AudioPlayer stream started successfully at native rate: {self.device_sample_rate}Hz.")
        except Exception as e:
            logger.error(f"Failed to start sounddevice OutputStream: {e}")
            self.stream = None

    def stop(self):
        """Stops the stream and releases PortAudio resources."""
        self.playing = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                logger.error(f"Error during audio stream cleanup: {e}")
            self.stream = None
        logger.info("AudioPlayer stream stopped.")

    def play_chunk(self, chunk: np.ndarray):
        """Queues a numpy array of float32 samples for playback."""
        # Ensure the stream is running
        if not self.playing:
            self.start()

        if chunk.dtype != np.float32:
            chunk = chunk.astype(np.float32)
            
        # Dynamically resample to the hardware's native sample rate if necessary
        # This prevents CoreAudio from renegotiating the format and dropping the volume!
        if self.stream is not None and self.device_sample_rate != self.sample_rate:
            orig_len = len(chunk)
            target_len = int((orig_len / self.sample_rate) * self.device_sample_rate)
            # Fast linear interpolation using numpy
            x_orig = np.linspace(0, 1, orig_len)
            x_target = np.linspace(0, 1, target_len)
            chunk = np.interp(x_target, x_orig, chunk).astype(np.float32)

        self.audio_queue.put(chunk)

    def interrupt(self):
        """Instantly flushes all queued audio buffers and silences the speaker."""
        logger.info("Interrupting playback: flushing audio queue and clearing active buffers.")
        
        # Set the interrupted flag to force the callback to output zeros immediately
        self.interrupted.set()
        
        # Drain the thread-safe queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
                
        # Clear the active play buffer
        with self.chunk_lock:
            self.current_chunk = np.array([], dtype=np.float32)
            
        # Clear the interrupted flag so subsequent play requests work
        self.interrupted.clear()
        
        # Destroy the PortAudio stream completely to prevent deadlocks when the
        # microphone is subsequently opened (e.g. during Force Listen profile switch).
        self.stop()

    def is_speaking(self) -> bool:
        """Returns True if there is audio actively playing or queued in the buffer."""
        if self.stream is None or not self.playing:
            return False
        try:
            if not self.stream.active:
                return False
        except Exception:
            pass
            
        with self.chunk_lock:
            has_data = len(self.current_chunk) > 0 or not self.audio_queue.empty()
            
        if has_data:
            # Check heartbeat to see if PortAudio callback is actually firing.
            # Stalls happen if the OS switches Bluetooth profiles under a running stream.
            import time
            if time.time() - self.last_callback_time > 1.2:
                logger.warning("AudioPlayer callback heartbeat lost. Stream has stalled. Self-healing...")
                self.stop()
                return False
            return True
            
        return False

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info: Any, status: sd.CallbackFlags):
        """PortAudio real-time callback requesting frames from the audio buffer."""
        import time
        self.last_callback_time = time.time()
        
        if status:
            logger.debug(f"PortAudio callback status: {status}")

        # If interrupted, write zeros (silence) and return immediately
        if self.interrupted.is_set():
            outdata.fill(0)
            return

        with self.chunk_lock:
            # Accumulate frames from the queue if the current chunk is smaller than requested frames
            while len(self.current_chunk) < frames:
                try:
                    next_chunk = self.audio_queue.get_nowait()
                    self.current_chunk = np.concatenate([self.current_chunk, next_chunk])
                except queue.Empty:
                    break

            # If we have enough samples, write them to outdata and advance buffer
            if len(self.current_chunk) >= frames:
                outdata[:, 0] = self.current_chunk[:frames]
                self.current_chunk = self.current_chunk[frames:]
            else:
                # Pad with zeros (silence) if queue is empty
                outdata[:, 0] = np.pad(self.current_chunk, (0, frames - len(self.current_chunk)), mode='constant')
                self.current_chunk = np.array([], dtype=np.float32)
