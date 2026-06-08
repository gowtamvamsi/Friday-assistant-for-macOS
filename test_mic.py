import time
from audio.vad_capture import SpeechCapture
import numpy as np
sc = SpeechCapture()
sc.calibrate()
print(f"Calibrated threshold: {sc.silence_threshold}")

sr, idx = sc._get_device_settings()
chunks = int(sc.chunk_size * sr / sc.sample_rate)
stream = sc.pa.open(format=8, channels=1, rate=sr, input=True, input_device_index=idx if idx != -1 else None, frames_per_buffer=chunks)

print("Speak now!")
for _ in range(20):
    data = stream.read(chunks, exception_on_overflow=False)
    audio = np.frombuffer(data, dtype=np.int16)
    rms = np.sqrt(np.mean(np.square(audio.astype(np.float32))))
    print(f"RMS: {rms}")
    time.sleep(0.1)

stream.stop_stream()
stream.close()
sc.terminate()
