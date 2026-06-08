import pyaudio
import numpy as np
import time

pa = pyaudio.PyAudio()

try:
    stream = pa.open(format=8, channels=1, rate=16000, input=True, frames_per_buffer=512)
    print("Opened stream natively at 16000Hz with CoreAudio resampling.")
    print("Speak now!")
    for _ in range(20):
        data = stream.read(512, exception_on_overflow=False)
        audio = np.frombuffer(data, dtype=np.int16)
        rms = np.sqrt(np.mean(np.square(audio.astype(np.float32))))
        print(f"RMS: {rms}")
        time.sleep(0.1)
    stream.stop_stream()
    stream.close()
except Exception as e:
    print(f"Failed: {e}")

pa.terminate()
