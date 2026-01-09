from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import requests

from .chunker import extract_chunks, flush_buffer


@dataclass
class LLMSettings:
    base_url: str
    model: str
    temperature: float


class LLMStreamWorker(threading.Thread):
    def __init__(
        self,
        settings: LLMSettings,
        messages: List[Dict[str, str]],
        on_chunk: Callable[[str], None],
        on_error: Callable[[str], None],
        on_done: Callable[[], None],
        cancel_event: threading.Event,
    ) -> None:
        super().__init__(daemon=True)
        self.settings = settings
        self.messages = messages
        self.on_chunk = on_chunk
        self.on_error = on_error
        self.on_done = on_done
        self.cancel_event = cancel_event
        self._response: Optional[requests.Response] = None

    def run(self) -> None:
        buffer = ""
        try:
            self._response = requests.post(
                f"{self.settings.base_url}/chat/completions",
                headers={"Content-Type": "application/json"},
                data=json.dumps(
                    {
                        "model": self.settings.model,
                        "temperature": self.settings.temperature,
                        "stream": True,
                        "messages": self.messages,
                    }
                ),
                stream=True,
                timeout=60,
            )
            self._response.raise_for_status()
            for line in self._response.iter_lines(decode_unicode=True):
                if self.cancel_event.is_set():
                    break
                if not line:
                    continue
                if line.startswith("data: "):
                    payload = line[len("data: ") :].strip()
                else:
                    payload = line.strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = data.get("choices", [{}])[0].get("delta", {}).get("content")
                if not delta:
                    continue
                buffer += delta
                chunks, buffer = extract_chunks(buffer)
                for chunk in chunks:
                    if self.cancel_event.is_set():
                        break
                    self.on_chunk(chunk)
            if not self.cancel_event.is_set():
                for chunk in flush_buffer(buffer):
                    self.on_chunk(chunk)
        except Exception as exc:  # noqa: BLE001
            if not self.cancel_event.is_set():
                self.on_error(str(exc))
        finally:
            self.on_done()

    def cancel(self) -> None:
        self.cancel_event.set()
        if self._response is not None:
            try:
                self._response.close()
            except Exception:  # noqa: BLE001
                pass
