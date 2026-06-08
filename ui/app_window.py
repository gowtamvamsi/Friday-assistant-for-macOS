import sys
import os
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QLineEdit,
    QLabel,
    QFrame,
    QGridLayout,
    QSplitter
)
from PyQt5.QtGui import QColor, QFont, QTextCursor
from PyQt5.QtCore import Qt

# Adjust import path if needed to ensure we can run it as python3 -m ui.app_window
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.socket_client import SocketClient

class AppWindow(QMainWindow):
    """The main testing GUI window for Friday Assistant."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Friday Assistant - Developer Testing Console")
        self.resize(1000, 650)
        self.setup_ui()
        
        # Initialize background socket client
        self.client = SocketClient()
        self.client.state_changed.connect(self.on_state_changed)
        self.client.token_received.connect(self.on_token_received)
        self.client.direct_tool_result.connect(self.on_direct_tool_result)
        self.client.chat_cleared.connect(self.on_chat_cleared)
        self.client.log_received.connect(self.on_log_received)
        self.client.connected_status.connect(self.on_connected_status)
        self.client.start()

    def setup_ui(self):
        """Builds the layout and styles the interface with dark-theme aesthetics."""
        # Main central widget
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        # Main layout is a horizontal splitter for sidebar and chat pane
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # -------------------------------------------------------------
        # Sidebar Panel (Left)
        # -------------------------------------------------------------
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(20)

        # 1. Title and Connection Status
        title_label = QLabel("FRIDAY ASSISTANT")
        title_label.setFont(QFont("SF Pro Display", 16, QFont.Bold))
        title_label.setStyleSheet("color: #7f5af0; margin-bottom: 2px;")
        sidebar_layout.addWidget(title_label)

        self.status_indicator = QLabel("Disconnected")
        self.status_indicator.setFont(QFont("Inter", 11, QFont.Bold))
        self.status_indicator.setStyleSheet("color: #ff5e5b; background-color: #1a1518; border-radius: 6px; padding: 4px 8px;")
        sidebar_layout.addWidget(self.status_indicator)

        # 2. Phase 3 Acoustic Pipeline Monitor
        phase3_frame = QFrame()
        phase3_frame.setStyleSheet("background-color: #16161a; border: 1px solid #24262f; border-radius: 10px;")
        phase3_layout = QVBoxLayout(phase3_frame)
        phase3_layout.setContentsMargins(12, 12, 12, 12)
        
        p3_title = QLabel("Phase 3: Acoustic Monitor")
        p3_title.setFont(QFont("Inter", 12, QFont.Bold))
        p3_title.setStyleSheet("color: #94a1b2;")
        phase3_layout.addWidget(p3_title)

        # State indicator row
        state_row = QHBoxLayout()
        self.state_dot = QFrame()
        self.state_dot.setFixedSize(14, 14)
        self.state_dot.setStyleSheet("background-color: #72757e; border-radius: 7px;")
        state_row.addWidget(self.state_dot)

        self.state_label = QLabel("Waiting for backend...")
        self.state_label.setFont(QFont("Inter", 11, QFont.Bold))
        self.state_label.setStyleSheet("color: #fffffe;")
        state_row.addWidget(self.state_label)
        state_row.addStretch()
        phase3_layout.addLayout(state_row)

        # Force Listen Button
        self.force_listen_btn = QPushButton("Force Listen")
        self.force_listen_btn.setObjectName("forceBtn")
        self.force_listen_btn.setToolTip("Bypass the wake word and trigger voice recording immediately.")
        self.force_listen_btn.clicked.connect(self.on_force_listen)
        phase3_layout.addWidget(self.force_listen_btn)

        sidebar_layout.addWidget(phase3_frame)

        # 2b. Phase 4 Speech Synthesis Monitor
        phase4_frame = QFrame()
        phase4_frame.setStyleSheet("background-color: #16161a; border: 1px solid #24262f; border-radius: 10px;")
        phase4_layout = QVBoxLayout(phase4_frame)
        phase4_layout.setContentsMargins(12, 12, 12, 12)

        p4_title = QLabel("Phase 4: Speech Synthesis")
        p4_title.setFont(QFont("Inter", 12, QFont.Bold))
        p4_title.setStyleSheet("color: #94a1b2;")
        phase4_layout.addWidget(p4_title)

        self.tts_input = QLineEdit()
        self.tts_input.setPlaceholderText("Enter text to synthesize...")
        self.tts_input.setText("Hello, this is a manual test of the local Kokoro MLX voice engine.")
        self.tts_input.returnPressed.connect(self.on_synthesize_play_clicked)
        phase4_layout.addWidget(self.tts_input)

        self.synthesize_btn = QPushButton("Synthesize & Play")
        self.synthesize_btn.setObjectName("primaryBtn")
        self.synthesize_btn.clicked.connect(self.on_synthesize_play_clicked)
        phase4_layout.addWidget(self.synthesize_btn)

        sidebar_layout.addWidget(phase4_frame)

        # 3. Phase 1 Manual Tools Module
        phase1_frame = QFrame()
        phase1_frame.setStyleSheet("background-color: #16161a; border: 1px solid #24262f; border-radius: 10px;")
        phase1_layout = QVBoxLayout(phase1_frame)
        phase1_layout.setContentsMargins(12, 12, 12, 12)

        p1_title = QLabel("Phase 1: Manual Tools")
        p1_title.setFont(QFont("Inter", 12, QFont.Bold))
        p1_title.setStyleSheet("color: #94a1b2;")
        phase1_layout.addWidget(p1_title)

        grid = QGridLayout()
        grid.setSpacing(8)

        # Audio tool buttons
        btn_mute = QPushButton("Mute Vol")
        btn_mute.clicked.connect(lambda: self.client.send_execute_tool("mute_volume", {}))
        grid.addWidget(btn_mute, 0, 0)

        btn_unmute = QPushButton("Unmute Vol")
        btn_unmute.clicked.connect(lambda: self.client.send_execute_tool("unmute_volume", {}))
        grid.addWidget(btn_unmute, 0, 1)

        btn_status = QPushButton("Vol Status")
        btn_status.clicked.connect(lambda: self.client.send_execute_tool("get_volume_status", {}))
        grid.addWidget(btn_status, 1, 0)

        btn_list = QPushButton("List Apps")
        btn_list.clicked.connect(lambda: self.client.send_execute_tool("list_running_applications", {}))
        grid.addWidget(btn_list, 1, 1)

        # App controls
        btn_notes = QPushButton("Open Notes")
        btn_notes.clicked.connect(lambda: self.client.send_execute_tool("open_application", {"app_name": "Notes"}))
        grid.addWidget(btn_notes, 2, 0)

        btn_notes_close = QPushButton("Close Notes")
        btn_notes_close.clicked.connect(lambda: self.client.send_execute_tool("close_application", {"app_name": "Notes"}))
        grid.addWidget(btn_notes_close, 2, 1)

        btn_safari = QPushButton("Open Safari")
        btn_safari.clicked.connect(lambda: self.client.send_execute_tool("open_application", {"app_name": "Safari"}))
        grid.addWidget(btn_safari, 3, 0)

        btn_safari_close = QPushButton("Close Safari")
        btn_safari_close.clicked.connect(lambda: self.client.send_execute_tool("close_application", {"app_name": "Safari"}))
        grid.addWidget(btn_safari_close, 3, 1)

        phase1_layout.addLayout(grid)
        sidebar_layout.addWidget(phase1_frame)
        sidebar_layout.addStretch()

        # Add sidebar to splitter
        splitter.addWidget(sidebar)

        # -------------------------------------------------------------
        # Chat & Logs Panel (Right)
        # -------------------------------------------------------------
        chat_pane = QWidget()
        chat_layout = QVBoxLayout(chat_pane)
        chat_layout.setContentsMargins(20, 20, 20, 20)
        chat_layout.setSpacing(12)

        # Header with actions
        header_row = QHBoxLayout()
        chat_title = QLabel("Phase 2: Cognitive Chat Console")
        chat_title.setFont(QFont("Inter", 14, QFont.Bold))
        chat_title.setStyleSheet("color: #fffffe;")
        header_row.addWidget(chat_title)
        header_row.addStretch()

        clear_btn = QPushButton("Clear Console")
        clear_btn.clicked.connect(self.on_clear_console)
        header_row.addWidget(clear_btn)
        chat_layout.addLayout(header_row)

        # Console text area
        self.chatConsole = QTextEdit()
        self.chatConsole.setObjectName("chatConsole")
        self.chatConsole.setReadOnly(True)
        self.chatConsole.setFont(QFont("Menlo", 12))
        chat_layout.addWidget(self.chatConsole)

        # Input box row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.inputField = QLineEdit()
        self.inputField.setPlaceholderText("Type a natural language command here (e.g., 'set volume to 40')...")
        self.inputField.returnPressed.connect(self.on_send_chat)
        input_row.addWidget(self.inputField)

        send_btn = QPushButton("Send")
        send_btn.setObjectName("primaryBtn")
        send_btn.clicked.connect(self.on_send_chat)
        input_row.addWidget(send_btn)
        chat_layout.addLayout(input_row)

        # Add chat pane to splitter
        splitter.addWidget(chat_pane)

        # Set stretch factors
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)

        # Apply application-wide styles
        self.apply_styles()

    def apply_styles(self):
        """Loads and applies style sheet variables."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121318;
            }
            QFrame#sidebar {
                background-color: #0c0d10;
                border-right: 1px solid #1a1c23;
            }
            QLabel {
                color: #fffffe;
            }
            QPushButton {
                background-color: #1a1c23;
                color: #fffffe;
                border: 1px solid #2e303f;
                border-radius: 8px;
                padding: 6px 12px;
                font-family: 'Inter';
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #2e303f;
                border: 1px solid #484b62;
            }
            QPushButton:pressed {
                background-color: #121318;
            }
            QPushButton#primaryBtn {
                background-color: #7f5af0;
                border: 1px solid #7f5af0;
                font-weight: bold;
                padding: 6px 18px;
            }
            QPushButton#primaryBtn:hover {
                background-color: #6246ea;
            }
            QPushButton#forceBtn {
                background-color: #2cb67d;
                border: 1px solid #2cb67d;
                color: #fffffe;
                font-weight: bold;
                margin-top: 8px;
                padding: 8px;
            }
            QPushButton#forceBtn:hover {
                background-color: #249567;
            }
            QTextEdit#chatConsole {
                background-color: #16161a;
                border: 1px solid #24262f;
                border-radius: 10px;
                padding: 14px;
                color: #fffffe;
                line-height: 1.4;
            }
            QLineEdit {
                background-color: #1a1c23;
                border: 1px solid #2e303f;
                border-radius: 8px;
                padding: 8px 12px;
                color: #fffffe;
                font-family: 'Inter';
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #7f5af0;
            }
        """)

    # -------------------------------------------------------------
    # Socket Event Handlers
    # -------------------------------------------------------------
    def on_connected_status(self, connected: bool):
        """Updates UI status depending on TCP socket connection status."""
        if connected:
            self.status_indicator.setText("Connected to Backend")
            self.status_indicator.setStyleSheet("color: #2cb67d; background-color: #131d1a; border-radius: 6px; padding: 4px 8px;")
        else:
            self.status_indicator.setText("Offline (Reconnecting...)")
            self.status_indicator.setStyleSheet("color: #ff5e5b; background-color: #1a1518; border-radius: 6px; padding: 4px 8px;")
            self.state_label.setText("Waiting for backend...")
            self.state_dot.setStyleSheet("background-color: #72757e; border-radius: 7px;")

    def on_state_changed(self, state: str):
        """Updates the visual state display in real-time.

        Args:
            state (str): The state string broadcasted by the server.
        """
        self.state_label.setText(state.replace("_", " "))
        
        # Color codes:
        # IDLE = Slate Gray (#72757e)
        # WAITING_FOR_WAKE_WORD = Bright Green (#2cb67d)
        # VOICE_ACTIVITY_DETECTED = Yellow/Amber (#e2a85c)
        # SILENCE_THRESHOLD_REACHED = Orange (#ff8906)
        # TRANSCRIBING = Purple (#7f5af0)
        # GENERATING = Pink/Purple (#ff007f or #7f5af0)
        
        color_mapping = {
            "IDLE": "#72757e",
            "WAITING_FOR_WAKE_WORD": "#2cb67d",
            "VOICE_ACTIVITY_DETECTED": "#e2a85c",
            "SILENCE_THRESHOLD_REACHED": "#ff8906",
            "TRANSCRIBING": "#ff007f",
            "GENERATING": "#9d4edd",
            "SYNTHESIZING_AUDIO": "#ff9f43",
            "SPEAKING": "#7f5af0"
        }
        color = color_mapping.get(state, "#72757e")
        self.state_dot.setStyleSheet(f"background-color: {color}; border-radius: 7px;")

    def on_token_received(self, token: str):
        """Streams incoming token chunks straight into the console QTextEdit."""
        cursor = self.chatConsole.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(token)
        self.chatConsole.ensureCursorVisible()

    def on_log_received(self, log_content: str):
        """Appends formatted thought blocks or tool execution status reports."""
        cursor = self.chatConsole.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(log_content)
        self.chatConsole.ensureCursorVisible()

    def on_direct_tool_result(self, result: str):
        """Appends the direct tool output with visual distinction."""
        cursor = self.chatConsole.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        html_msg = (
            f'<br><span style="color: #e2a85c; font-weight: bold;">⚙️ [Direct Tool Executed]</span><br>'
            f'<span style="color: #94a1b2;">{result}</span><br>'
        )
        cursor.insertHtml(html_msg)
        self.chatConsole.ensureCursorVisible()

    def on_chat_cleared(self):
        """Clears the console text widget."""
        self.chatConsole.clear()

    # -------------------------------------------------------------
    # User Input Triggers
    # -------------------------------------------------------------
    def on_send_chat(self):
        """Fires off user text queries directly to the server backend."""
        text = self.inputField.text().strip()
        if not text:
            return
            
        cursor = self.chatConsole.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        # Clear line spacing and insert formatted User tag
        cursor.insertHtml(f'<br><b style="color: #2cb67d;">user > </b><span style="color: #fffffe;">{text}</span><br>')
        self.chatConsole.ensureCursorVisible()

        self.client.send_chat(text)
        self.inputField.clear()

    def on_force_listen(self):
        """Tells the server to trigger capture right now."""
        # Immediate visual feedback in console
        cursor = self.chatConsole.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(
            '<br><span style="color: #2cb67d; font-weight: bold;">'
            '🎙️ Force Listen triggered — speak now...</span><br>'
        )
        self.chatConsole.ensureCursorVisible()

        sent = self.client.send_force_listen()
        if not sent:
            cursor = self.chatConsole.textCursor()
            cursor.movePosition(QTextCursor.End)
            cursor.insertHtml(
                '<span style="color: #ff5e5b;">'
                '⚠️ Could not send Force Listen — backend not connected.</span><br>'
            )
            self.chatConsole.ensureCursorVisible()

    def on_synthesize_play_clicked(self):
        """Requests backend to synthesize and play the text entered in the TTS input field."""
        text = self.tts_input.text().strip()
        if not text:
            return
            
        cursor = self.chatConsole.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(
            f'<br><span style="color: #7f5af0; font-weight: bold;">'
            f'🔊 Requesting synthesis: "{text}"</span><br>'
        )
        self.chatConsole.ensureCursorVisible()
        self.client.send_tts_play(text)

    def on_clear_console(self):
        """Sends command to clear history."""
        self.client.send_clear_history()
        self.chatConsole.clear()

    def closeEvent(self, event):
        """Ensures the background thread is shut down cleanly on close."""
        self.client.stop()
        self.client.wait()
        event.accept()


def main():
    app = QApplication(sys.argv)
    
    # Optional styling settings
    app.setStyle("Fusion")
    
    win = AppWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
