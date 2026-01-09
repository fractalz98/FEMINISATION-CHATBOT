from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Optional

import pyttsx3


@dataclass
class TTSSettings:
    voice_id: Optional[str]
    rate: int
    volume: float


class TTSWorker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._queue: "queue.Queue[tuple[str, TTSSettings]]" = queue.Queue()
        self._stop_event = threading.Event()
        self._engine = pyttsx3.init()
        self._ready = threading.Event()

    def run(self) -> None:
        self._ready.set()
        while not self._stop_event.is_set():
            try:
                text, settings = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if self._stop_event.is_set():
                break
            if settings.voice_id:
                self._engine.setProperty("voice", settings.voice_id)
            self._engine.setProperty("rate", settings.rate)
            self._engine.setProperty("volume", settings.volume)
            self._engine.say(text)
            self._engine.runAndWait()

    def wait_until_ready(self) -> None:
        self._ready.wait(timeout=5)

    def enqueue(self, text: str, settings: TTSSettings) -> None:
        if not text.strip():
            return
        self._queue.put((text.strip(), settings))

    def stop(self) -> None:
        self._stop_event.set()
        self._clear_queue()
        try:
            self._engine.stop()
        except Exception:  # noqa: BLE001
            pass

    def flush(self) -> None:
        self._clear_queue()
        try:
            self._engine.stop()
        except Exception:  # noqa: BLE001
            pass

    def _clear_queue(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

    def available_voices(self) -> list:
        return self._engine.getProperty("voices")
