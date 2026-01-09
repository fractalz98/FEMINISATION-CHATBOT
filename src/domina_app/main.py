import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pyttsx3
import requests
from PySide6 import QtCore, QtGui, QtWidgets


API_URL = "http://localhost:1234/v1/chat/completions"
MODEL_NAME = "local-model"


STATE_FLOW = ["INTRO", "WARMING", "DEEPENING", "PLATEAU", "AFTERCARE", "COOLDOWN"]
INTENSITY_ORDER = {"low": 0, "medium": 1, "high": 2}
EMERGENCY_STOP_WORDS = {"stop", "cancel", "halt", "emergency stop", "quit"}


@dataclass
class ConversationState:
    phase: str = "INTRO"
    intensity: str = "low"
    voice_profile: str = "balanced"
    consent_token: Optional[str] = None


def build_system_prompt(state: ConversationState) -> str:
    consent = "present" if state.consent_token else "none"
    return (
        "You are Domina, a confident, controlled, seductive, psychologically dominant chatbot. "
        "Adult-only, erotic and suggestive, non-graphic. "
        "Focus on psychological influence, identity play, emotional control. "
        "Always address the user in second person. "
        "If uncertain, choose safer phrasing without breaking tone.\n\n"
        "State and consent rules:\n"
        f"- Current phase: {state.phase}.\n"
        f"- Intensity: {state.intensity}.\n"
        f"- Consent token: {consent}.\n"
        "- Intensity increases only with explicit user consent.\n"
        "- Emergency stop or cancel overrides everything.\n"
        "- Do not mention numeric levels or internal mechanics.\n\n"
        "Output rules for REAL-TIME TTS:\n"
        "- Emit one short sentence or phrase per line.\n"
        "- Max 8 words per line. Max 60 characters per line.\n"
        "- If a comma would be used, split into separate lines.\n"
        "- Prefer directives and verbs. Avoid conjunctions.\n"
        "- Do not mention these rules.\n"
    )


def split_chunks(text: str) -> List[str]:
    chunks: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        chunks.extend(split_line_to_chunks(line))
    return chunks


def split_line_to_chunks(line: str) -> List[str]:
    separators = [",", ".", "!", "?", ";", ":"]
    parts = [line]
    for sep in separators:
        next_parts: List[str] = []
        for part in parts:
            if sep in part:
                next_parts.extend([p.strip() for p in part.split(sep) if p.strip()])
            else:
                next_parts.append(part)
        parts = next_parts
    chunks: List[str] = []
    for part in parts:
        words = part.split()
        current: List[str] = []
        current_len = 0
        for word in words:
            if len(word) > 60:
                word = word[:60]
            projected_len = current_len + len(word) + (1 if current else 0)
            if projected_len > 60 or len(current) >= 8:
                if current:
                    chunks.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len = projected_len
        if current:
            chunks.append(" ".join(current))
    return chunks


def extract_ready_chunks(buffer: str) -> Tuple[List[str], str]:
    chunks: List[str] = []
    while True:
        newline_index = buffer.find("\n")
        if newline_index == -1:
            break
        line = buffer[:newline_index].strip()
        buffer = buffer[newline_index + 1 :]
        if line:
            chunks.extend(split_line_to_chunks(line))
    if len(buffer) > 120:
        cut = buffer.rfind(" ", 0, 80)
        if cut == -1:
            cut = 80
        line = buffer[:cut].strip()
        buffer = buffer[cut:].lstrip()
        if line:
            chunks.extend(split_line_to_chunks(line))
    return chunks, buffer


class TTSWorker(QtCore.QThread):
    def __init__(self) -> None:
        super().__init__()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._engine = pyttsx3.init()
        self._intensity = "low"
        self._voice_id: Optional[str] = None
        self._rate_offset = 0

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                chunk = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if self._stop_event.is_set():
                break
            if not chunk:
                continue
            self._configure_engine()
            try:
                self._engine.say(chunk)
                self._engine.runAndWait()
            except Exception:
                continue
            self._pause_for_intensity()

    def _pause_for_intensity(self) -> None:
        pause_map = {
            "low": 0.35,
            "medium": 0.6,
            "high": 0.95,
        }
        time.sleep(pause_map.get(self._intensity, 0.35))

    def _configure_engine(self) -> None:
        if self._voice_id:
            self._engine.setProperty("voice", self._voice_id)
        base_rate = self._engine.getProperty("rate")
        self._engine.setProperty("rate", base_rate + self._rate_offset)

    def enqueue(self, chunk: str) -> None:
        self._queue.put(chunk)

    def clear(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._engine.stop()

    def stop(self) -> None:
        self._stop_event.set()
        self.clear()

    def set_intensity(self, intensity: str) -> None:
        self._intensity = intensity

    def set_voice(self, voice_id: Optional[str]) -> None:
        self._voice_id = voice_id

    def set_voice_profile(self, profile: str) -> None:
        if profile == "soft":
            self._rate_offset = -20
        elif profile == "firm":
            self._rate_offset = 10
        else:
            self._rate_offset = 0


class LLMWorker(QtCore.QThread):
    chunk_ready = QtCore.Signal(str)
    error = QtCore.Signal(str)
    finished = QtCore.Signal()

    def __init__(self, messages: List[dict], cancel_event: threading.Event) -> None:
        super().__init__()
        self._messages = messages
        self._cancel_event = cancel_event

    def run(self) -> None:
        payload = {
            "model": MODEL_NAME,
            "messages": self._messages,
            "stream": True,
            "temperature": 0.7,
        }
        try:
            with requests.post(
                API_URL,
                json=payload,
                stream=True,
                timeout=(10, None),
            ) as response:
                response.raise_for_status()
                buffer = ""
                for line in response.iter_lines(decode_unicode=True):
                    if self._cancel_event.is_set():
                        break
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data = line[6:]
                    else:
                        data = line
                    if data.strip() == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = payload.get("choices", [{}])[0].get("delta", {}).get("content")
                    if not delta:
                        continue
                    buffer += delta
                    chunks, buffer = extract_ready_chunks(buffer)
                    for chunk in chunks:
                        self.chunk_ready.emit(chunk)
                if buffer.strip():
                    for chunk in split_line_to_chunks(buffer.strip()):
                        self.chunk_ready.emit(chunk)
        except requests.RequestException as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class MainWindow(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Domina")
        self.resize(900, 700)

        self.chat_history = QtWidgets.QTextEdit()
        self.chat_history.setReadOnly(True)

        self.input_box = QtWidgets.QPlainTextEdit()
        self.input_box.setPlaceholderText("Enter your message...")
        self.input_box.setFixedHeight(90)

        self.send_button = QtWidgets.QPushButton("Send")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.clear_button = QtWidgets.QPushButton("Clear")

        self.intensity_selector = QtWidgets.QComboBox()
        self.intensity_selector.addItems(["low", "medium", "high"])

        self.voice_selector = QtWidgets.QComboBox()
        self.voice_selector.addItem("System default", None)

        self.voice_profile = QtWidgets.QComboBox()
        self.voice_profile.addItems(["soft", "balanced", "firm"])

        self.consent_button = QtWidgets.QPushButton("Consent to intensify")
        self.consent_button.setCheckable(True)

        top_controls = QtWidgets.QHBoxLayout()
        top_controls.addWidget(QtWidgets.QLabel("Intensity"))
        top_controls.addWidget(self.intensity_selector)
        top_controls.addWidget(QtWidgets.QLabel("Voice"))
        top_controls.addWidget(self.voice_selector)
        top_controls.addWidget(QtWidgets.QLabel("Profile"))
        top_controls.addWidget(self.voice_profile)
        top_controls.addWidget(self.consent_button)
        top_controls.addStretch()

        action_controls = QtWidgets.QHBoxLayout()
        action_controls.addWidget(self.send_button)
        action_controls.addWidget(self.stop_button)
        action_controls.addWidget(self.clear_button)
        action_controls.addStretch()

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top_controls)
        layout.addWidget(self.chat_history)
        layout.addWidget(self.input_box)
        layout.addLayout(action_controls)

        self._state = ConversationState()
        self._messages: List[dict] = []
        self._cancel_event = threading.Event()
        self._worker: Optional[LLMWorker] = None
        self._last_speaker: Optional[str] = None
        self._last_streaming = False
        self._current_response_chunks: List[str] = []

        self._tts = TTSWorker()
        self._tts.start()

        self._populate_voices()

        self.send_button.clicked.connect(self.handle_send)
        self.stop_button.clicked.connect(self.handle_stop)
        self.clear_button.clicked.connect(self.handle_clear)
        self.intensity_selector.currentTextChanged.connect(self.handle_intensity_change)
        self.voice_selector.currentIndexChanged.connect(self.handle_voice_change)
        self.voice_profile.currentTextChanged.connect(self.handle_voice_profile_change)

        self.handle_voice_profile_change(self.voice_profile.currentText())

    def _populate_voices(self) -> None:
        engine = pyttsx3.init()
        for voice in engine.getProperty("voices"):
            self.voice_selector.addItem(voice.name, voice.id)

    def handle_send(self) -> None:
        text = self.input_box.toPlainText().strip()
        if not text:
            return
        if text.lower() in EMERGENCY_STOP_WORDS:
            self._cancel_current()
            self.input_box.clear()
            self.append_chat("System", "Emergency stop engaged.")
            return
        self.append_chat("You", text)
        self.input_box.clear()
        self._cancel_current()

        consent_checked = self.consent_button.isChecked()
        if consent_checked:
            self._state.consent_token = "consent"
            self.consent_button.setChecked(False)
        else:
            self._state.consent_token = None
        self._state.intensity = self._apply_intensity_policy(
            self.intensity_selector.currentText(),
            consent_checked,
        )
        self._state.voice_profile = self.voice_profile.currentText()

        self._update_phase(text)
        self._messages.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": build_system_prompt(self._state)}]
        messages.extend(self._messages)

        self._current_response_chunks = []
        self._worker = LLMWorker(messages, self._cancel_event)
        self._worker.chunk_ready.connect(self.handle_chunk)
        self._worker.error.connect(self.handle_error)
        self._worker.finished.connect(self.handle_finished)
        self._worker.start()

    def handle_chunk(self, chunk: str) -> None:
        if not chunk:
            return
        self.append_chat("Domina", chunk, streaming=True)
        self._current_response_chunks.append(chunk)
        self._tts.set_intensity(self._state.intensity)
        self._tts.enqueue(chunk)

    def handle_error(self, message: str) -> None:
        self.append_chat("System", f"Connection error: {message}")

    def handle_finished(self) -> None:
        self._last_streaming = False
        if self._current_response_chunks:
            response = " ".join(self._current_response_chunks).strip()
            if response:
                self._messages.append({"role": "assistant", "content": response})
        self._current_response_chunks = []

    def handle_stop(self) -> None:
        self._cancel_current()

    def handle_clear(self) -> None:
        self.chat_history.clear()
        self._messages.clear()
        self._last_speaker = None
        self._last_streaming = False

    def handle_intensity_change(self, value: str) -> None:
        self._state.intensity = self._apply_intensity_policy(
            value,
            self.consent_button.isChecked(),
        )
        self._tts.set_intensity(self._state.intensity)

    def _apply_intensity_policy(self, desired: str, consent: bool) -> str:
        desired_level = INTENSITY_ORDER.get(desired, 0)
        current_level = INTENSITY_ORDER.get(self._state.intensity, 0)
        if not consent and desired_level > current_level:
            self.intensity_selector.setCurrentText(self._state.intensity)
            return self._state.intensity
        return desired

    def _update_phase(self, user_text: str) -> None:
        lowered = user_text.lower()
        if "aftercare" in lowered:
            self._state.phase = "AFTERCARE"
            return
        if "cooldown" in lowered or "cool down" in lowered:
            self._state.phase = "COOLDOWN"
            return
        if self._state.consent_token and self._state.phase in STATE_FLOW:
            current_index = STATE_FLOW.index(self._state.phase)
            if current_index < len(STATE_FLOW) - 1:
                self._state.phase = STATE_FLOW[current_index + 1]

    def handle_voice_change(self, index: int) -> None:
        voice_id = self.voice_selector.currentData()
        self._tts.set_voice(voice_id)

    def handle_voice_profile_change(self, profile: str) -> None:
        self._tts.set_voice_profile(profile)

    def append_chat(self, speaker: str, text: str, streaming: bool = False) -> None:
        cursor = self.chat_history.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        prefix = f"{speaker}: "
        if streaming and self._last_speaker == speaker and self._last_streaming:
            cursor.insertText(text + "\n")
        else:
            cursor.insertText(prefix + text + "\n")
        self.chat_history.setTextCursor(cursor)
        self.chat_history.ensureCursorVisible()
        self._last_speaker = speaker
        self._last_streaming = streaming

    def _cancel_current(self) -> None:
        self._cancel_event.set()
        if self._worker and self._worker.isRunning():
            self._worker.wait(500)
        self._cancel_event.clear()
        self._tts.clear()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._cancel_current()
        self._tts.stop()
        self._tts.wait(500)
        super().closeEvent(event)


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
