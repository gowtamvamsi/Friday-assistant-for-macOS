import time
import pyaudio
import numpy as np

pa = pyaudio.PyAudio()
idx = 5  # MacBook Pro Microphone
info = pa.get_device_info_by_index(idx)
sr = int(info['defaultSampleRate'])
chunks = int(512 * sr / 16000)

print(f"Opening device {idx}: {info['name']} at {sr}Hz")
stream = pa.open(format=8, channels=1, rate=sr, input=True, input_device_index=idx, frames_per_buffer=chunks)

print("Speak now!")
for _ in range(20):
    data = stream.read(chunks, exception_on_overflow=False)
    audio = np.frombuffer(data, dtype=np.int16)
    rms = np.sqrt(np.mean(np.square(audio.astype(np.float32))))
    print(f"RMS: {rms}")
    time.sleep(0.1)

stream.stop_stream()
stream.close()
pa.terminate()
