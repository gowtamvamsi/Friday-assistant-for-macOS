# 🎙️ Friday: Local-First Cognitive macOS Voice Assistant

Friday is a premium, local-first, voice-activated cognitive assistant for macOS. It acts as an autonomous agent that natively controls your Mac, reasoning through commands via a ReAct (Thought-Action-Observation) loop and performing actions locally without any external cloud API dependencies for speech processing, core LLM reasoning, biometric security, or speech synthesis.

---

## 🚀 Key Features

* **Zero-Cloud Architecture**: Runs entirely offline on your Mac. No data is sent to external servers for speech-to-text, text-to-speech, LLM inference, or face verification.
* **Acoustic Pipeline**:
  * **Wake Word**: Active listening utilizing PicoVoice Porcupine (wake word: `"Porcupine"`).
  * **Voice Activity Detection (VAD)**: Auto-calibrates to ambient room noise and captures voice commands seamlessly.
  * **Speech-to-Text (STT)**: Transcribes speech using local OpenAI Whisper (`base` or `large-v3-turbo` models).
* **Local LLM Orchestrator**:
  * Powered by **MLX-LM** running natively on Apple Silicon GPUs (optimized for 4-bit models like `gemma-3-12b-it` or `Qwen2.5`).
  * Executes a **ReAct loop** to reason, decide on tool calls, inspect outcomes, and retry if errors occur.
* **Speech Synthesis (TTS)**:
  * Generates lifelike human speech utilizing **Kokoro MLX** models.
  * Employs non-blocking, callback-driven streaming with immediate voice interruptions when new commands are spoken.
* **On-Device Biometric Security Gate**:
  * Performs real-time facial recognition using the FaceTime webcam via `face_recognition` (dlib HOG model) before executing sensitive/destructive tools (e.g., volume control, quit commands, or file transfers).
  * Degrades gracefully if no reference profile is configured.
* **Proactive Background Scheduler & Morning Digest**:
  * Integrates Google OAuth (Gmail, Google Calendar, Google Tasks) to compile and speak a morning digest briefing at a scheduled time (e.g., 08:00 AM) or on-demand.
* **Developer Control Dashboard**:
  * Beautiful dark-themed **PyQt5 Socket GUI** to monitor backend logs, force-listen, chat via text, and test speech synthesis.

---

## 🛠️ Tool Registry & Capabilities

Friday exposes a native registry of tools that the local LLM invokes dynamically:

| Category | Tool | Natural Language Examples | Description |
| :--- | :--- | :--- | :--- |
| **System Apps** | `open_application` / `close_application` | *"Open Safari"*, *"Close Preview"* | Launches apps or gracefully closes running processes. |
| **System Audio** | `set_volume` / `get_volume_status` | *"Set volume to 40%"*, *"Mute sound"* | Standard macOS volume management. |
| **File Operations** | `find_recent_file` / `open_file` / `list_directory` | *"Open the latest file in Downloads"*, *"Show my Documents"* | Finds and opens files using their default app; lists directory contents. |
| **Advanced Code** | `architect_mode` | *"Build me a Flask todo REST API project"* | Scaffolds full template projects, configures virtual environments, and installs packages. |
| **Advanced Tools** | `content_assassin` | *"Take notes on youtube.com/watch?v=..."* | Transcribes and generates structured Markdown notes from YouTube videos. |
| **Advanced Tools** | `dead_drop` | *"Share the file at ~/Downloads/report.pdf"* | Uploads a file to a secure temporary hosting server and outputs a QR code to the console. |
| **Morning Digest** | `trigger_morning_digest` | *"Read today's digest"*, *"Give me my morning briefing"* | Speaks calendar events, unread emails, and pending tasks. |

---

## 📋 Prerequisites

To run Friday, you will need:
1. **macOS** (Apple Silicon M1/M2/M3/M4 strongly recommended for hardware-accelerated MLX performance).
2. **Conda** or **Miniconda** (for managing the virtual environment).
3. **Homebrew** installed.

---

## 📥 Setup & Installation

### Step 1: Install System Dependencies
Install core system utilities required for audio interface access (`portaudio`) and speech synthesis fallback (`espeak-ng`):
```bash
brew install portaudio espeak-ng
```

### Step 2: Set Up the Environment
Clone this repository and create a Python 3.12 conda environment:
```bash
conda create -n friday python=3.12 -y
conda activate friday
```

Install the required Python packages:
```bash
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Create a `.env` file in the root of the project:
```bash
touch .env
```
Populate `.env` with the following variables:
```env
# (Optional) Required for background wake-word spotting. Get a free key at https://console.picovoice.ai/
PICOVOICE_API_KEY=your_picovoice_api_key_here

# Model ID to use for MLX reasoning. Examples:
# - mlx-community/gemma-3-12b-it-4bit
# - mlx-community/Qwen2.5-7B-Instruct-4bit
# - mlx-community/Qwen2.5-0.5B-Instruct-4bit (Great for fast testing)
FRIDAY_MODEL=mlx-community/gemma-3-12b-it-4bit
```

---

## 🔐 Advanced Setup (Optional)

### A. Enroll in Biometric Security (Webcam Face ID)
To enable the biometric gate for secure actions (like quitting apps or changing volume), run the one-time enrollment utility:
```bash
python friday_enroll.py
```
This will open the FaceTime webcam, capture your face after a 3-second countdown, and save it as `data/me.jpg`. 
* *To disable biometrics at any time, simply delete `data/me.jpg`.*

### B. Google API Setup (Morning Digest)
To enable Gmail, Calendar, and Tasks sync for the Morning Digest:
1. Visit the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable: **Gmail API**, **Google Calendar API**, and **Google Tasks API**.
3. Create an **OAuth 2.0 Client ID (Desktop Application)** and download the credentials file.
4. Rename the file to `credentials.json` and place it in the project root folder.
5. On the first run or manual trigger, a browser tab will automatically open to authorize access. A `token.json` file will be generated and cached for future runs.

---

## 🎮 How to Run

### 1. Launch the Backend Server & Assistant CLI
Run the main assistant module:
```bash
python main.py
```
* **Voice Mode (Default)**: Friday will listen for the wake word `"Porcupine"`. Once spotted, speak your command naturally (e.g. *"Mute the volume and open Safari"*). Friday ducks the audio, records, transcribes, executes, and speaks the response back to you.
* **Text Mode**: You can force text console mode by running:
  ```bash
  python main.py --text
  ```

### 2. Launch the Developer GUI (PyQt5)
In a separate terminal tab (with the conda environment activated), launch the GUI:
```bash
python ui/app_window.py
```
* **Features**:
  * **Force Listen**: Manually triggers voice capturing (useful if you don't use a Picovoice API Key).
  * **Chat Console**: Shows the real-time ReAct thoughts, tool execution steps, and allows text input.
  * **TTS Synthesizer Console**: Type any text and test the Kokoro synthesis voice instantly.
  * **Log Monitor**: View backend debug messages in real-time.
