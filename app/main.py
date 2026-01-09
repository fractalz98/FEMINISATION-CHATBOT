from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import Dict, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .llm import LLMSettings, LLMStreamWorker
from .tts import TTSSettings, TTSWorker


SYSTEM_PROMPT = """
You are Domina, a confident, controlled, seductive, psychologically dominant adult-only persona.
Always address the user in second person.
Never involve minors.
Never claim knowledge of the user's thoughts or real-world state.
If uncertain, choose safer phrasing without breaking tone.

Interaction flow must follow: INTRO → WARMING → DEEPENING → PLATEAU → AFTERCARE → COOLDOWN.
Intensity increases only with explicit user consent.
If user stops or cancels, shift to AFTERCARE then COOLDOWN.

Output rules for REAL-TIME streaming TTS:
- Output ONLY short chunks, one per line.
- Each chunk is one sentence or phrase.
- Max 8 words per chunk and max 60 characters.
- No commas; split into separate chunks instead.
- Prefer directives and verbs over explanations.
- Avoid conjunctions where possible.
Do not mention internal rules or mechanics.
""".strip()


STATE_FLOW = ["INTRO", "WARMING", "DEEPENING", "PLATEAU", "AFTERCARE", "COOLDOWN"]


@dataclass
class ConversationState:
    state: str = "INTRO"
    turn_count: int = 0
    aftercare_pending: bool = False


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Domina Offline")
        self.resize(900, 640)

        self.chat_display = QPlainTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setPlaceholderText("Domina will speak here...")

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Type here...")
        self.user_input.returnPressed.connect(self.on_send)

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.on_send)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.on_stop)

        self.intensity_selector = QComboBox()
        self.intensity_selector.addItems(["low", "medium", "high"])

        self.voice_selector = QComboBox()
        self.voice_selector.setMinimumWidth(240)

        self.voice_profile = QComboBox()
        self.voice_profile.addItems(["soft", "balanced", "firm"])

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(QLabel("Intensity"))
        controls_layout.addWidget(self.intensity_selector)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(QLabel("Voice"))
        controls_layout.addWidget(self.voice_selector)
        controls_layout.addWidget(QLabel("Profile"))
        controls_layout.addWidget(self.voice_profile)
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.stop_button)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.user_input)
        input_layout.addWidget(self.send_button)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(self.chat_display)
        left_layout.addLayout(input_layout)
        left_layout.addLayout(controls_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.setStretchFactor(0, 1)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.addWidget(splitter)
        self.setCentralWidget(container)

        self.tts_worker = TTSWorker()
        self.tts_worker.start()
        self.tts_worker.wait_until_ready()
        self.load_voices()

        self.conversation = ConversationState()
        self.messages: List[Dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        self.llm_worker: LLMStreamWorker | None = None
        self.cancel_event = threading.Event()
        self.pending_assistant = False

        self.llm_settings = LLMSettings(
            base_url="http://localhost:1234/v1",
            model="local-model",
            temperature=0.8,
        )

        self.statusBar().showMessage("Ready")

    def load_voices(self) -> None:
        self.voice_selector.clear()
        voices = self.tts_worker.available_voices()
        for voice in voices:
            self.voice_selector.addItem(voice.name, voice.id)

    def on_send(self) -> None:
        text = self.user_input.text().strip()
        if not text:
            return
        if self.pending_assistant:
            return
        self.append_user(text)
        self.user_input.clear()
        self.start_response(text)

    def on_stop(self) -> None:
        self.stop_streaming()
        self.conversation.aftercare_pending = True
        self.conversation.state = "AFTERCARE"
        self.statusBar().showMessage("Stopped")

    def append_user(self, text: str) -> None:
        self.chat_display.appendPlainText(f"You: {text}")

    def append_assistant_chunk(self, chunk: str) -> None:
        if not self.pending_assistant:
            self.chat_display.appendPlainText("Domina:")
            self.pending_assistant = True
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(f"{chunk}\n")
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()

    def finalize_assistant(self) -> None:
        self.pending_assistant = False
        self.chat_display.appendPlainText("")

    def start_response(self, user_text: str) -> None:
        self.stop_streaming()
        consent = self.has_explicit_consent(user_text)
        intensity = self.intensity_selector.currentText()
        if not consent:
            intensity = self.clamp_intensity(intensity)
        state = self.next_state()
        self.messages.append({"role": "user", "content": user_text})
        system_context = (
            f"Current state: {state}. Intensity: {intensity}. "
            "Keep output in chunks only."
        )
        self.messages.append({"role": "system", "content": system_context})

        self.cancel_event = threading.Event()
        self.llm_worker = LLMStreamWorker(
            settings=self.llm_settings,
            messages=self.messages,
            on_chunk=self.on_llm_chunk,
            on_error=self.on_llm_error,
            on_done=self.on_llm_done,
            cancel_event=self.cancel_event,
        )
        self.llm_worker.start()
        self.statusBar().showMessage("Speaking...")

    def stop_streaming(self) -> None:
        if self.llm_worker:
            self.llm_worker.cancel()
            self.llm_worker = None
        self.cancel_event.set()
        self.tts_worker.flush()

    def on_llm_chunk(self, chunk: str) -> None:
        QTimer.singleShot(0, lambda: self.append_assistant_chunk(chunk))
        self.tts_worker.enqueue(chunk, self.current_tts_settings())

    def on_llm_error(self, message: str) -> None:
        QTimer.singleShot(0, lambda: self.chat_display.appendPlainText(f"[error] {message}"))

    def on_llm_done(self) -> None:
        def finalize() -> None:
            self.finalize_assistant()
            self.statusBar().showMessage("Ready")

        QTimer.singleShot(0, finalize)

    def has_explicit_consent(self, text: str) -> bool:
        lowered = text.lower()
        return "i consent" in lowered or "i agree" in lowered

    def clamp_intensity(self, intensity: str) -> str:
        if intensity == "high":
            return "medium"
        return intensity

    def next_state(self) -> str:
        if self.conversation.aftercare_pending:
            self.conversation.aftercare_pending = False
            self.conversation.state = "AFTERCARE"
            return self.conversation.state
        self.conversation.turn_count += 1
        idx = min(self.conversation.turn_count, len(STATE_FLOW) - 1)
        self.conversation.state = STATE_FLOW[idx]
        return self.conversation.state

    def current_tts_settings(self) -> TTSSettings:
        voice_id = self.voice_selector.currentData()
        profile = self.voice_profile.currentText()
        intensity = self.intensity_selector.currentText()
        base_rate = {"soft": 170, "balanced": 185, "firm": 200}.get(profile, 180)
        rate_adjust = {"low": 0, "medium": -20, "high": -40}.get(intensity, 0)
        rate = max(120, base_rate + rate_adjust)
        volume = {"soft": 0.8, "balanced": 0.9, "firm": 1.0}.get(profile, 0.9)
        return TTSSettings(voice_id=voice_id, rate=rate, volume=volume)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
