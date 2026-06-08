import socket
import json
import logging
import time
from PyQt5.QtCore import QThread, pyqtSignal

logger = logging.getLogger("friday.socket_client")

class SocketClient(QThread):
    """PyQt5 background thread that manages the TCP connection to port 8492.

    Reads line-delimited JSON payloads from the Friday backend socket server
    and emits Qt signals to safely update the GUI thread.
    """
    state_changed = pyqtSignal(str)
    token_received = pyqtSignal(str)
    direct_tool_result = pyqtSignal(str)
    chat_cleared = pyqtSignal()
    log_received = pyqtSignal(str)
    connected_status = pyqtSignal(bool)

    def __init__(self, host: str = "localhost", port: int = 8492):
        super().__init__()
        self.host = host
        self.port = port
        self.socket = None
        self.running = True
        self.connected = False

    def run(self):
        """Continuously attempts to connect and process incoming socket messages."""
        buffer = ""
        while self.running:
            if not self.connected:
                try:
                    self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.socket.connect((self.host, self.port))
                    self.connected = True
                    self.connected_status.emit(True)
                    logger.info(f"Connected to Friday backend on {self.host}:{self.port}")
                except Exception as e:
                    self.connected = False
                    self.connected_status.emit(False)
                    # Retry connection every 2 seconds
                    time.sleep(2)
                    continue

            try:
                # Read data chunk from socket
                data = self.socket.recv(4096)
                if not data:
                    # Connection closed by server
                    logger.warning("Connection closed by server.")
                    self.handle_disconnect()
                    continue

                buffer += data.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        self.parse_message(line)
            except socket.error as e:
                logger.warning(f"Socket error: {e}")
                self.handle_disconnect()
            except Exception as e:
                logger.error(f"Unexpected error in socket read thread: {e}")
                self.handle_disconnect()

    def handle_disconnect(self):
        """Resets status when disconnected and flags reconnect."""
        self.connected = False
        self.connected_status.emit(False)
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        # Short sleep before attempting reconnect
        time.sleep(1)

    def parse_message(self, line: str):
        """Parses a single line-delimited JSON message and emits appropriate signals.

        Args:
            line (str): The raw JSON string line.
        """
        try:
            msg = json.loads(line)
            msg_type = msg.get("type")

            if msg_type == "state":
                self.state_changed.emit(msg.get("value", "IDLE"))
            elif msg_type == "token":
                self.token_received.emit(msg.get("value", ""))
            elif msg_type == "log":
                self.log_received.emit(msg.get("value", ""))
            elif msg_type == "direct_tool_result":
                self.direct_tool_result.emit(msg.get("value", ""))
            elif msg_type == "clear_history_ack":
                self.chat_cleared.emit()
            else:
                logger.debug(f"Received unknown socket message: {msg}")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to decode message line: '{line}'. Error: {e}")

    def send_command(self, payload: dict) -> bool:
        """Sends a JSON command to the backend socket server.

        Args:
            payload (dict): The command payload structure to send.

        Returns:
            bool: True if sent successfully, False otherwise.
        """
        if not self.connected or not self.socket:
            logger.warning("Cannot send command: not connected to server.")
            return False

        try:
            # Suffix with newline for line-delimited protocol
            message = json.dumps(payload) + "\n"
            self.socket.sendall(message.encode("utf-8"))
            return True
        except Exception as e:
            logger.error(f"Error sending command payload: {e}")
            self.handle_disconnect()
            return False

    def send_chat(self, text: str):
        """Sends a natural language chat query to Friday's orchestrator."""
        self.send_command({"type": "chat", "text": text})

    def send_execute_tool(self, name: str, args: dict):
        """Sends a direct tool execution request."""
        self.send_command({"type": "execute_tool", "name": name, "arguments": args})

    def send_force_listen(self) -> bool:
        """Sends a force listen command to bypass wake word detection."""
        return self.send_command({"type": "force_listen"})

    def send_clear_history(self):
        """Sends a request to clear orchestrator history."""
        self.send_command({"type": "clear_history"})

    def send_tts_play(self, text: str):
        """Sends a request to synthesize and play arbitrary text."""
        self.send_command({"type": "tts_play", "text": text})


    def stop(self):
        """Stops the socket client loop and closes connections."""
        self.running = False
        self.handle_disconnect()
