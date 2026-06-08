import shlex
import inspect
import json
import logging
import sys
import os
import argparse
import socket
import threading
import queue
from typing import Any, Dict, List, Tuple
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up clean logging to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
# Suppress noisy external logs
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("friday.main")

# Import registry, tools, and cognitive engine
from tools.registry import registry
from engine.mlx_runtime import MLXRuntime
from engine.orchestrator import Orchestrator
import tools.file_ops  # noqa: F401 — registers find_recent_file, open_file, list_directory

# Import Phase 4 TTS engine and Audio player
from audio import TTSEngine, AudioPlayer

# ── Phase 5: Advanced Autonomy Imports ────────────────────────────────────────
import tools.advanced_automation as _advanced_auto  # noqa: F401 (registers tools on import)
from agents.scheduled_tasks import ScheduledTaskRunner, run_morning_digest

# Phase 4 TTS & Audio Player resources
tts_engine = TTSEngine()
audio_player = AudioPlayer()
tts_sentence_queue = queue.Queue()
abort_generation_event = threading.Event()

# Global lock to synchronize access to the Orchestrator (safety first)
orchestrator_lock = threading.Lock()

@registry.register
def trigger_morning_digest() -> dict:
    """Triggers and reads your morning digest briefing (emails, calendar, tasks) immediately.

    Returns:
        dict: A status dictionary containing "status" and a "message".
    """
    logger.info("Triggering morning digest manually.")
    
    # Run on a separate thread to prevent blocking the LLM's ReAct loop response
    def run_digest():
        run_morning_digest(
            tts_sentence_queue=tts_sentence_queue,
            audio_player=audio_player,
            allowed_event=None
        )
    
    threading.Thread(target=run_digest, daemon=True).start()
    
    return {
        "status": "success",
        "message": "Morning digest briefing has been triggered and is now playing."
    }

# ANSI Escape Sequences for terminal styling
COLOR_HEADER = "\033[95m"
COLOR_BLUE = "\033[94m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_RED = "\033[91m"
COLOR_BOLD = "\033[1m"
COLOR_RESET = "\033[0m"

# -------------------------------------------------------------
# Socket Server Daemon (Port 8492)
# -------------------------------------------------------------
class SocketServer:
    """Runs a background TCP server on port 8492.

    Allows the testing GUI to execute tools directly, bypass mic input
    with text chat queries, trigger a force-listen event, and receive
    real-time system status and generation token broadcasts.
    """
    def __init__(self, host: str = "127.0.0.1", port: int = 8492):
        self.host = host
        self.port = port
        self.clients: List[socket.socket] = []
        self.clients_lock = threading.Lock()
        self.server_socket = None
        self.running = False
        
        # References populated dynamically
        self.orchestrator = None
        self.orchestrator_lock = None
        self.work_queue = None
        self.force_listen_event = None
        self.history: List[Dict[str, str]] = []

    def start(self):
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            logger.info(f"Socket server running on {self.host}:{self.port}")
            threading.Thread(target=self._accept_loop, daemon=True).start()
        except Exception as e:
            logger.error(f"Could not start Socket Server: {e}")

    def _accept_loop(self):
        while self.running:
            try:
                client_sock, client_addr = self.server_socket.accept()
                logger.info(f"GUI Client connected from: {client_addr}")
                with self.clients_lock:
                    self.clients.append(client_sock)
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except Exception as e:
                if self.running:
                    logger.debug(f"Socket accept error: {e}")
                break

    def _handle_client(self, client_sock: socket.socket):
        buffer = ""
        # Send initial idle/waiting status on connection
        self.send_to_client(client_sock, {"type": "state", "value": "WAITING_FOR_WAKE_WORD"})
        
        while self.running:
            try:
                data = client_sock.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._process_message(client_sock, line)
            except Exception:
                break

        with self.clients_lock:
            if client_sock in self.clients:
                self.clients.remove(client_sock)
        try:
            client_sock.close()
        except Exception:
            pass
        logger.info("GUI Client disconnected.")

    def send_to_client(self, client_sock: socket.socket, payload: dict):
        try:
            msg = json.dumps(payload) + "\n"
            client_sock.sendall(msg.encode("utf-8"))
        except Exception:
            pass

    def broadcast(self, payload: dict):
        """Sends a JSON message to all currently connected clients."""
        with self.clients_lock:
            for client in list(self.clients):
                try:
                    msg = json.dumps(payload) + "\n"
                    client.sendall(msg.encode("utf-8"))
                except Exception:
                    if client in self.clients:
                        self.clients.remove(client)

    def _process_message(self, client_sock: socket.socket, line: str):
        try:
            data = json.loads(line)
            msg_type = data.get("type")

            if msg_type == "execute_tool":
                name = data.get("name")
                args = data.get("arguments", {})
                logger.info(f"GUI requested direct tool run: '{name}' with args {args}")
                
                # Execute tool directly bypassing LLM
                result = registry.execute(name, args)
                status = result.get("status", "error")
                message = result.get("message", "")
                
                self.send_to_client(client_sock, {
                    "type": "direct_tool_result",
                    "value": f"[{status.upper()}] {message}"
                })

            elif msg_type == "chat":
                text = data.get("text", "")
                if self.work_queue is not None:
                    # Voice Loop Mode: queue it so the main thread processes it sequentially
                    self.work_queue.put({"type": "chat_command", "text": text})
                else:
                    # Text Console Mode: execute in a separate thread since main thread blocks on stdin
                    threading.Thread(target=self._run_chat_turn, args=(text,), daemon=True).start()

            elif msg_type == "force_listen":
                logger.info("GUI requested Force Listen: interrupting active speech/generation.")
                abort_generation_event.set()
                audio_player.interrupt()
                while not tts_sentence_queue.empty():
                    try:
                        tts_sentence_queue.get_nowait()
                        tts_sentence_queue.task_done()
                    except queue.Empty:
                        break
                if self.force_listen_event is not None:
                    self.force_listen_event.set()

            elif msg_type == "tts_play":
                text = data.get("text", "")
                logger.info(f"GUI requested manual TTS play: '{text}'")
                abort_generation_event.set()
                audio_player.interrupt()
                while not tts_sentence_queue.empty():
                    try:
                        tts_sentence_queue.get_nowait()
                        tts_sentence_queue.task_done()
                    except queue.Empty:
                        break
                tts_sentence_queue.put(text)

            elif msg_type == "clear_history":
                self.history.clear()
                self.send_to_client(client_sock, {"type": "clear_history_ack"})

        except Exception as e:
            logger.error(f"Error processing socket packet: {e}")

    def _run_chat_turn(self, text: str):
        """Helper to run a chat turn on a background thread when in Text console mode."""
        with self.orchestrator_lock:
            self.broadcast({"type": "state", "value": "GENERATING"})
            
            def stream_cb(token: str):
                self.broadcast({"type": "token", "value": token})

            final_answer, self.history = self.orchestrator.run_turn(
                user_input=text,
                history=self.history,
                stream_callback=stream_cb
            )
            self.broadcast({"type": "token", "value": "\n"})
            self.broadcast({"type": "state", "value": "IDLE"})

socket_server = SocketServer()

from audio.wake_word import WakeWordDetector
import sounddevice as sd
import numpy as np

class MockWakeWordDetector:
    """Mock wake word detector that blocks until a GUI force-listen event is triggered."""
    def __init__(self, force_listen_event: threading.Event):
        self.force_listen_event = force_listen_event

    def wait_for_wake_word(self) -> bool:
        logger.info("Awaiting Force Listen command from GUI (wake word detection disabled)...")
        socket_server.broadcast({"type": "state", "value": "WAITING_FOR_WAKE_WORD"})
        # Wait until the force-listen event is set
        self.force_listen_event.wait()
        self.force_listen_event.clear()
        logger.info("Force Listen triggered!")
        return True

    def terminate(self):
        pass

class GUIWakeWordDetector(WakeWordDetector):
    """Subclass of WakeWordDetector that intercepts the wait loop to check for force-listening flags."""
    def __init__(self, api_key: str | None = None, keyword: str = "porcupine", force_listen_event: threading.Event = None, audio_manager=None):
        super().__init__(api_key, keyword)
        self.force_listen_event = force_listen_event
        self.audio_manager = audio_manager

    def wait_for_wake_word(self) -> bool:
        self.init_porcupine()
        sample_rate = self.porcupine.sample_rate
        frame_length = self.porcupine.frame_length

        if self.audio_manager:
            self.audio_manager.capture_a2dp_volume()

        try:
            input_stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype='int16',
                blocksize=frame_length
            )
            input_stream.start()
            if self.audio_manager:
                self.audio_manager.sync_hfp_volume()
        except Exception as e:
            logger.error(f"Failed to open audio input stream for wake word listener: {e}")
            return False

        logger.info(f"Friday is listening for the wake word '{self.keyword}'...")

        try:
            while True:
                # Check if force listen has been triggered via Socket
                if self.force_listen_event and self.force_listen_event.is_set():
                    logger.info("Bypassing wake word detection: Force Listen Triggered.")
                    self.force_listen_event.clear()
                    return True

                data, overflowed = input_stream.read(frame_length)
                audio_frame = data.flatten()

                result = self.porcupine.process(audio_frame)
                if result >= 0:
                    logger.info(f"Wake word '{self.keyword}' detected!")
                    return True
        except KeyboardInterrupt:
            logger.info("Wake word listener interrupted.")
            return False
        except Exception as e:
            logger.error(f"Error in wake-word detection loop: {e}")
            return False
        finally:
            input_stream.stop()
            input_stream.close()

# -------------------------------------------------------------
# Console Helpers
# -------------------------------------------------------------
def print_welcome(model_id: str, voice_mode: bool = False):
    print(f"\n{COLOR_HEADER}{COLOR_BOLD}==================================================")
    print("   FRIDAY ASSISTANT - Phase 3 Acoustic Console   ")
    print(f"=================================================={COLOR_RESET}")
    print(f"Friday is online. Model: {COLOR_GREEN}{model_id}{COLOR_RESET}")
    print(f"Input mode: {COLOR_GREEN}{'VOICE (Always-On)' if voice_mode else 'TEXT (Interactive)'}{COLOR_RESET}")
    
    if voice_mode:
        print("\nHow to interact:")
        print(f"  1. Say the wake word: {COLOR_BOLD}“Porcupine”{COLOR_RESET}")
        print("  2. Wait for the indicator: 🎙️  Listening...")
        print("  3. Speak your command. Friday will stop recording once you pause.")
        print("  4. System volume will restore, and Friday will execute your request.")
        print(f"\nCommands:")
        print(f"  Press {COLOR_YELLOW}Ctrl+C{COLOR_RESET} to exit the application safely.")
    else:
        print("\nHow to interact:")
        print(f"  - {COLOR_BOLD}Natural Language:{COLOR_RESET} Just type your request (e.g., 'mute volume and open Notes')")
        print(f"  - {COLOR_BOLD}Slash Commands:{COLOR_RESET}")
        print(f"    {COLOR_BLUE}/tool <name> [args...]{COLOR_RESET} - Execute a registered tool directly (bypasses LLM)")
        print(f"    {COLOR_BLUE}/list{COLOR_RESET}                  - List all registered tools and their schemas")
        print(f"    {COLOR_BLUE}/clear{COLOR_RESET}                 - Clear current conversation history")
        print(f"    {COLOR_BLUE}/model{COLOR_RESET}                 - Check model ID information")
        print(f"    {COLOR_BLUE}/help{COLOR_RESET}                  - Show this instructions panel")
        print(f"    {COLOR_BLUE}/exit{COLOR_RESET}                  - Close Friday console")
    print("-" * 50)
    print(f"{COLOR_YELLOW}💡 Tip: You can set the env variable FRIDAY_MODEL to run other models.")
    print("   e.g. export FRIDAY_MODEL=\"mlx-community/Qwen2.5-0.5B-Instruct-4bit\" for fast testing.{COLOR_RESET}")
    print("-" * 50)

def parse_val(val: str) -> Any:
    """Intelligently converts CLI input strings to proper Python types."""
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1]
    return val

def handle_direct_tool(command_str: str):
    """Executes a tool directly from the registry (Phase 1 testing fallback)."""
    try:
        parts = shlex.split(command_str)
    except ValueError as e:
        print(f"{COLOR_RED}Parsing Error: {str(e)}{COLOR_RESET}")
        return

    if not parts:
        print(f"{COLOR_RED}Error: No tool name specified.{COLOR_RESET}")
        return

    tool_name = parts[0]
    raw_args = parts[1:]

    func = registry.get_tool(tool_name)
    if not func:
        print(f"{COLOR_RED}Error: Tool '{tool_name}' is not registered.{COLOR_RESET}")
        return

    sig = inspect.signature(func)
    param_names = list(sig.parameters.keys())
    
    kwargs: Dict[str, Any] = {}
    
    for i, arg in enumerate(raw_args):
        if "=" in arg:
            key, val = arg.split("=", 1)
            kwargs[key.strip()] = parse_val(val.strip())
        else:
            if i < len(param_names):
                kwargs[param_names[i]] = parse_val(arg)

    print(f"\n⚙️  Executing '{tool_name}' directly with args: {kwargs}")
    result = registry.execute(tool_name, kwargs)
    
    status = result.get("status", "error")
    message = result.get("message", "No message returned.")
    data = result.get("data", None)
    
    if status == "success":
        print(f"{COLOR_GREEN}SUCCESS: {message}{COLOR_RESET}")
        if data:
            print(f"Data: {json.dumps(data, indent=2)}")
    else:
        print(f"{COLOR_RED}ERROR: {message}{COLOR_RESET}")

def stream_output(token: str):
    """Stream token outputs to standard output in real-time."""
    sys.stdout.write(token)
    sys.stdout.flush()

# -------------------------------------------------------------
# Console Mode Loop
# -------------------------------------------------------------
def run_text_console(model_id: str, runtime: MLXRuntime, orchestrator: Orchestrator):
    """Runs the interactive text-input CLI console from Phase 2."""
    print_welcome(model_id, voice_mode=False)
    history: List[Dict[str, str]] = []
    socket_server.history = history
    
    while True:
        try:
            sys.stdout.write(f"\n{COLOR_BOLD}user > {COLOR_RESET}")
            sys.stdout.flush()
            
            line = sys.stdin.readline()
            if not line: # EOF
                break
                
            line = line.strip()
            if not line:
                continue
                
            # Normalize command checking
            cmd_line = line.strip()
            lower_line = cmd_line.lower()
            
            if lower_line in ("exit", "quit", "clear", "model", "list", "help", "?"):
                cmd_line = "/" + lower_line
            elif lower_line.startswith("tool:"):
                cmd_line = "/tool " + cmd_line[5:].strip()
                
            # Process Commands
            if cmd_line.startswith("/"):
                cmd_parts = cmd_line.split(" ", 1)
                cmd = cmd_parts[0].lower()
                arg = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""
                
                if cmd == "/exit":
                    print(f"{COLOR_YELLOW}Exiting Friday. Goodbye!{COLOR_RESET}")
                    break
                elif cmd == "/clear":
                    history.clear()
                    socket_server.history = history
                    print(f"{COLOR_GREEN}Conversation history cleared.{COLOR_RESET}")
                elif cmd == "/model":
                    print(f"Active MLX Model ID: {COLOR_GREEN}{runtime.model_id}{COLOR_RESET}")
                    if runtime.model is not None:
                        print("Model status: Loaded in memory.")
                    else:
                        print("Model status: Not yet loaded (will lazy load on first query).")
                elif cmd == "/list":
                    print(f"\n{COLOR_BLUE}Registered Tools and JSON Schemas:{COLOR_RESET}")
                    for schema in registry.generate_all_schemas():
                        print(json.dumps(schema, indent=2))
                        print("-" * 30)
                elif cmd == "/tool":
                    if not arg:
                        print(f"{COLOR_RED}Error: /tool requires arguments (e.g., /tool set_volume level=20).{COLOR_RESET}")
                    else:
                        handle_direct_tool(arg)
                elif cmd in ("/help", "/?"):
                    print_welcome(runtime.model_id, voice_mode=False)
                else:
                    print(f"{COLOR_RED}Unknown slash command '{cmd}'. Type /help for instructions.{COLOR_RESET}")
            
            # Process Conversational Query (Natural Language via ReAct Orchestrator)
            else:
                print(f"\n{COLOR_BOLD}friday > {COLOR_RESET}", end="")
                
                if runtime.model is None:
                    print(f"\n{COLOR_YELLOW}(Lazy-loading '{runtime.model_id}'. Downloading weights if not cached...){COLOR_RESET}\nfriday > ", end="")
                
                socket_server.broadcast({"type": "state", "value": "GENERATING"})
                
                def combined_stream_callback(token: str):
                    stream_output(token)
                    socket_server.broadcast({"type": "token", "value": token})

                with orchestrator_lock:
                    final_answer, history = orchestrator.run_turn(
                        user_input=line,
                        history=history,
                        stream_callback=combined_stream_callback
                    )
                print()
                socket_server.broadcast({"type": "token", "value": "\n"})
                socket_server.broadcast({"type": "state", "value": "IDLE"})
                socket_server.history = history
                
        except KeyboardInterrupt:
            print(f"\n{COLOR_YELLOW}Use /exit or Ctrl+D to quit. Session interrupted.{COLOR_RESET}")
        except Exception as e:
            logger.exception("Exception in main text loop")
            print(f"\n{COLOR_RED}System error occurred: {str(e)}{COLOR_RESET}", file=sys.stderr)

# -------------------------------------------------------------
# Voice Mode Loop (Queue Driven)
# -------------------------------------------------------------
def wake_word_thread_fn(wake_detector: Any, work_queue: queue.Queue, allowed_event: threading.Event):
    """Background listener that spots the wake keyword and queues voice triggers safely."""
    import time
    while True:
        # Block until allowed to listen (prevents conflict during recording/generation)
        allowed_event.wait()
        time.sleep(0.5) # Give macOS audio system time to fully release the microphone
        try:
            triggered = wake_detector.wait_for_wake_word()
            if not triggered:
                logger.warning("Wake word detection failed or interrupted. Retrying in 2 seconds...")
                time.sleep(2.0)
                continue
            allowed_event.clear()
            work_queue.put({"type": "voice_command"})
        except Exception as e:
            logger.error(f"Error in wake word background thread: {e}")
            time.sleep(2.0)


class SentenceAccumulator:
    def __init__(self, sentence_queue: queue.Queue):
        self.queue = sentence_queue
        self.buffer = ""
        self.delimiters = {'.', '?', '!', '\n'}

    def add_token(self, token: str):
        self.buffer += token
        while True:
            idx = -1
            for d in self.delimiters:
                pos = self.buffer.find(d)
                if pos != -1:
                    if idx == -1 or pos < idx:
                        idx = pos
            
            if idx == -1:
                break
                
            sentence = self.buffer[:idx+1].strip()
            self.buffer = self.buffer[idx+1:]
            if sentence:
                self.queue.put(sentence)

    def flush(self):
        sentence = self.buffer.strip()
        if sentence:
            self.queue.put(sentence)
        self.buffer = ""

import re
class StreamTTSTranslator:
    def __init__(self, tts_sentence_queue: queue.Queue):
        self.queue = tts_sentence_queue
        self.accumulator = SentenceAccumulator(self.queue)
        self.full_response = ""
        self.seen_answer_tag = False
        self.answer_index = -1
        self.synthesized_anything = False

    def reset(self):
        self.full_response = ""
        self.seen_answer_tag = False
        self.answer_index = -1
        self.accumulator.buffer = ""
        self.synthesized_anything = False

    def add_token(self, token: str):
        self.full_response += token
        
        if not self.seen_answer_tag:
            match = re.search(r"Answer:\s*", self.full_response, re.IGNORECASE)
            if match:
                self.seen_answer_tag = True
                self.answer_index = match.end()
                self.synthesized_anything = True
                remaining = self.full_response[self.answer_index:]
                if remaining:
                    self.accumulator.add_token(remaining)
        else:
            self.accumulator.add_token(token)

    def flush(self, final_answer: str = ""):
        logger.info(f"StreamTTSTranslator.flush() called. seen_answer_tag={self.seen_answer_tag}, synthesized_anything={self.synthesized_anything}, final_answer='{final_answer}'")
        if self.seen_answer_tag:
            self.accumulator.flush()
        elif final_answer and not self.synthesized_anything:
            # We don't want to speak raw JSON action blocks if the LLM failed to answer properly
            # But we DO want to speak the final answer if it's a normal sentence, even if previous
            # steps in the orchestrator stream contained an Action!
            is_action_block = "action:" in final_answer.lower() and "{" in final_answer
            logger.info(f"Fallback check: is_action_block={is_action_block}")
            if not is_action_block and final_answer.strip():
                logger.info(f"TTS fallback: queuing entire final answer: '{final_answer}'")
                self.queue.put(final_answer.strip())
                self.synthesized_anything = True

def tts_worker_thread_fn():
    """Background worker that pulls sentences from the queue, synthesizes them, and streams them to the AudioPlayer."""
    import time
    while True:
        try:
            sentence = tts_sentence_queue.get()
            if sentence is None:
                break
            
            logger.info(f"TTS Worker: Synthesizing sentence: '{sentence}'")
            socket_server.broadcast({"type": "state", "value": "SYNTHESIZING_AUDIO"})
            
            try:
                # Start generation stream
                for chunk in tts_engine.generate_stream(sentence):
                    if abort_generation_event.is_set():
                        logger.info("TTS Worker: Interrupted during synthesis generation.")
                        break
                    
                    audio_player.play_chunk(chunk)
                    socket_server.broadcast({"type": "state", "value": "SPEAKING"})
            except Exception as e:
                logger.error(f"Error during TTS generation/playback: {e}")
            finally:
                tts_sentence_queue.task_done()
            
            # If the queue is empty, wait for playback to finish and reset state
            if tts_sentence_queue.empty():
                start_wait = time.time()
                while audio_player.is_speaking():
                    if time.time() - start_wait > 6.0:
                        logger.warning("TTS Worker: speaking loop timeout reached. Stopping player.")
                        audio_player.stop()
                        break
                    time.sleep(0.05)
                # Broadcast the appropriate idle state
                next_state = "WAITING_FOR_WAKE_WORD" if socket_server.work_queue is not None else "IDLE"
                socket_server.broadcast({"type": "state", "value": next_state})
                
        except Exception as e:
            logger.error(f"Error in TTS background worker thread loop: {e}")

def run_voice_loop(model_id: str, runtime: MLXRuntime, orchestrator: Orchestrator):


    """Runs the always-on acoustic pipeline listening for the wake word."""
    # Lazy load audio modules to catch dependency errors locally
    from audio import SpeechCapture, STTEngine, AudioManager

    print_welcome(model_id, voice_mode=True)
    
    # Initialize audio helpers
    audio_manager = AudioManager()
    stt_engine = STTEngine()
    speech_capture = SpeechCapture()
    
    # Queue and Synchronization
    work_queue = queue.Queue()
    force_listen_event = threading.Event()
    allowed_event = threading.Event()
    allowed_event.set() # Listening allowed initially

    api_key = os.getenv("PICOVOICE_API_KEY")
    if not api_key:
        logger.warning("\n" + "=" * 60 +
                       "\n⚠️  PICOVOICE_API_KEY is missing in your .env file! \n"
                       "Passive wake-word spotter is disabled.\n"
                       "Friday will run in 'Force Listen Only' mode (triggered via GUI).\n" +
                       "=" * 60 + "\n")
        wake_detector = MockWakeWordDetector(force_listen_event=force_listen_event)
    else:
        # Initialize the custom wake detector
        wake_detector = GUIWakeWordDetector(api_key=api_key, force_listen_event=force_listen_event, audio_manager=audio_manager)
    
    # Set references on socket server
    socket_server.work_queue = work_queue
    socket_server.force_listen_event = force_listen_event
    
    # Calibrate ambient noise baseline
    speech_capture.calibrate(calibration_duration=1.0)
    
    # Start wake word thread
    threading.Thread(
        target=wake_word_thread_fn,
        args=(wake_detector, work_queue, allowed_event),
        daemon=True
    ).start()
    
    # Create temp directory for recorded speech commands
    temp_dir = "./scratch"
    os.makedirs(temp_dir, exist_ok=True)
    temp_audio_path = os.path.join(temp_dir, "command.wav")
    
    history: List[Dict[str, str]] = []
    socket_server.history = history
    
    # Send initial state update
    socket_server.broadcast({"type": "state", "value": "WAITING_FOR_WAKE_WORD"})
    

                
    # Define the interruption callback
    def on_speech_start():
        logger.info("User speech detected! Interrupting Friday's speech.")
        abort_generation_event.set()
        audio_player.interrupt()
        while not tts_sentence_queue.empty():
            try:
                tts_sentence_queue.get_nowait()
                tts_sentence_queue.task_done()
            except queue.Empty:
                break

    translator = StreamTTSTranslator(tts_sentence_queue)

    try:
        while True:
            # Main thread blocks waiting for tasks (voice trigger or GUI text chat bypass)
            task = work_queue.get()
            
            # Lock out wake-word detection stream immediately during task execution
            allowed_event.clear()
            
            if task["type"] == "voice_command":
                # Step 2: [DISABLED] Duck macOS system audio (User explicitly requested volume to stay as is)
                socket_server.broadcast({"type": "state", "value": "VOICE_ACTIVITY_DETECTED"})
                
                # Capture the current volume before the microphone opens
                audio_manager.capture_a2dp_volume()
                
                # Step 3: Capture speech command with VAD
                print(f"\n{COLOR_GREEN}🎙️  Listening for command...{COLOR_RESET}")
                
                # IMPORTANT: Stop the active PortAudio output stream before opening the microphone!
                # If we leave the A2DP stream open while the microphone switches the hardware to HFP,
                # the PortAudio output stream silently stalls and deadlocks the entire application.
                audio_player.stop()
                
                captured = speech_capture.record_command(
                    temp_audio_path,
                    max_duration=10.0,
                    silence_duration_limit=1.5,
                    on_speech_start=on_speech_start,
                    on_mic_open=audio_manager.sync_hfp_volume
                )
                
                # Step 4: [DISABLED] Restore system audio
                socket_server.broadcast({"type": "state", "value": "SILENCE_THRESHOLD_REACHED"})
                # audio_manager.unduck()
                
                if not captured:
                    print(f"{COLOR_YELLOW}⚠️  No speech detected or recording timed out.{COLOR_RESET}")
                    socket_server.broadcast({"type": "log", "value": "⚠️ No speech detected — please speak clearly into your microphone.\n"})
                    socket_server.broadcast({"type": "state", "value": "WAITING_FOR_WAKE_WORD"})
                    allowed_event.set()
                    continue
                    
                # Step 5: Transcribe raw speech WAV file to text
                socket_server.broadcast({"type": "state", "value": "TRANSCRIBING"})
                print(f"{COLOR_YELLOW}⏳  Transcribing...{COLOR_RESET}")
                query = stt_engine.transcribe(temp_audio_path)
                
                if not query:
                    print(f"{COLOR_RED}⚠️  Speech could not be understood.{COLOR_RESET}")
                    socket_server.broadcast({"type": "state", "value": "WAITING_FOR_WAKE_WORD"})
                    allowed_event.set()
                    continue
                    
                # Print the transcription
                print(f"\n{COLOR_BOLD}user > {COLOR_RESET}{query}")
                socket_server.broadcast({"type": "log", "value": f"\nuser > {query}\n"})
                
                # Step 6: Feed transcribed query into ReAct Orchestrator loop
                socket_server.broadcast({"type": "state", "value": "GENERATING"})
                print(f"{COLOR_BOLD}friday > {COLOR_RESET}", end="")
                
                if runtime.model is None:
                    print(f"\n{COLOR_YELLOW}(Lazy-loading '{runtime.model_id}'. Downloading weights if not cached...){COLOR_RESET}\nfriday > ", end="")
                    socket_server.broadcast({"type": "log", "value": f"(Lazy-loading '{runtime.model_id}'...)\n"})
                
                # Reset TTS translator state for this turn
                translator.reset()
                abort_generation_event.clear()

                def socket_stream_callback(token: str):
                    stream_output(token)
                    socket_server.broadcast({"type": "token", "value": token})
                    translator.add_token(token)

                with orchestrator_lock:
                    final_answer, history = orchestrator.run_turn(
                        user_input=query,
                        history=history,
                        stream_callback=socket_stream_callback
                    )
                print()
                socket_server.broadcast({"type": "token", "value": "\n"})
                socket_server.history = history
                
                # Flush the translator to synthesize any final sentence remaining
                translator.flush(final_answer)

                # Block until synthesis and playback is complete
                logger.info("Waiting for TTS synthesis and playback to complete...")
                tts_sentence_queue.join()
                import time
                start_wait = time.time()
                while audio_player.is_speaking():
                    if time.time() - start_wait > 6.0:
                        logger.warning("Main Thread: speaking loop timeout reached. Stopping player.")
                        audio_player.stop()
                        break
                    time.sleep(0.05)

                
            elif task["type"] == "chat_command":
                query = task["text"]
                # Directly execute text bypass chat query
                socket_server.broadcast({"type": "state", "value": "GENERATING"})
                print(f"\n{COLOR_BOLD}user (GUI) > {COLOR_RESET}{query}")
                print(f"{COLOR_BOLD}friday > {COLOR_RESET}", end="")
                
                if runtime.model is None:
                    print(f"\n{COLOR_YELLOW}(Lazy-loading '{runtime.model_id}'. Downloading weights if not cached...){COLOR_RESET}\nfriday > ", end="")
                    socket_server.broadcast({"type": "log", "value": f"(Lazy-loading '{runtime.model_id}'...)\n"})

                # Reset TTS translator state for this turn
                translator.reset()
                abort_generation_event.clear()

                def socket_stream_callback(token: str):
                    stream_output(token)
                    socket_server.broadcast({"type": "token", "value": token})
                    translator.add_token(token)

                with orchestrator_lock:
                    final_answer, history = orchestrator.run_turn(
                        user_input=query,
                        history=history,
                        stream_callback=socket_stream_callback
                    )
                print()
                socket_server.broadcast({"type": "token", "value": "\n"})
                socket_server.history = history

                # Flush the translator to synthesize any final sentence remaining
                translator.flush(final_answer)

                # Block until synthesis and playback is complete
                logger.info("Waiting for TTS synthesis and playback to complete...")
                tts_sentence_queue.join()
                import time
                start_wait = time.time()
                while audio_player.is_speaking():
                    if time.time() - start_wait > 6.0:
                        logger.warning("Main Thread: speaking loop timeout reached. Stopping player.")
                        audio_player.stop()
                        break
                    time.sleep(0.05)
            
            # Task complete, restore idle listening state
            socket_server.broadcast({"type": "state", "value": "WAITING_FOR_WAKE_WORD"})
            allowed_event.set()
            
    finally:
        # Graceful cleanup of resources
        logger.info("Cleaning up acoustic pipeline audio streams...")
        wake_detector.terminate()
        speech_capture.terminate()
        # audio_manager.unduck() # Restore volume in case we exit while ducked

# -------------------------------------------------------------
# Main Entrypoint
# -------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Friday Assistant - Cognitive Voice Console")
    parser.add_argument(
        "--text", "-t",
        action="store_true",
        help="Run Friday in text-only interactive console mode"
    )
    args = parser.parse_args()

    # Load configuration
    model_id = os.environ.get("FRIDAY_MODEL", "mlx-community/gemma-3-12b-it-4bit")
    
    # Initialize runtime and orchestrator
    runtime = MLXRuntime(model_id=model_id)
    orchestrator = Orchestrator(runtime=runtime, registry=registry)
    
    # Link orchestrator and start background TCP server
    socket_server.orchestrator = orchestrator
    socket_server.orchestrator_lock = orchestrator_lock
    socket_server.start()

    # ── Phase 5: Wire Advanced Automation with shared LLM runtime ────────────
    _advanced_auto.set_runtime(runtime)
    logger.info("Phase 5: Advanced automation tools linked to LLM runtime.")

    # ── Phase 5: Wire Biometric Security Callback ────────────────────────────
    def _biometric_denied_callback(tool_name: str) -> None:
        """Called when biometric check fails — speaks an access denied alert."""
        tts_sentence_queue.put(f"Access denied. Biometric verification failed for {tool_name}.")

    orchestrator.on_security_failed = _biometric_denied_callback
    logger.info("Phase 5: Biometric security gate registered.")

    # ── Phase 5: Launch Scheduled Background Agents ──────────────────────────
    scheduler = ScheduledTaskRunner()

    # Register Morning Digest at 8:00 AM daily
    # It waits for the system to be idle before speaking
    def _morning_digest_job():
        import queue as _q
        run_morning_digest(
            tts_sentence_queue=tts_sentence_queue,
            audio_player=audio_player,
            allowed_event=None  # Will speak when TTS queue is free
        )

    scheduler.add_task(name="morning_digest", hour=8, minute=0, func=_morning_digest_job)
    scheduler.start()
    logger.info("Phase 5: Background scheduler started. Morning Digest registered at 08:00.")
    
    # Start background TTS worker thread
    threading.Thread(target=tts_worker_thread_fn, daemon=True).start()
    
    if args.text:
        run_text_console(model_id, runtime, orchestrator)
    else:
        # Start voice activation, falling back to text mode on error
        try:
            run_voice_loop(model_id, runtime, orchestrator)
        except Exception as e:
            print(f"\n{COLOR_RED}{COLOR_BOLD}⚠️  Acoustic Pipeline Error: {str(e)}{COLOR_RESET}")
            print(f"{COLOR_YELLOW}Falling back to text-only console mode...{COLOR_RESET}\n")
            run_text_console(model_id, runtime, orchestrator)

if __name__ == "__main__":
    main()
