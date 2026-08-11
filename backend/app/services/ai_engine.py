"""Google Gemini chatbot engine with conversational memory and human-handoff detection."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_none

from app.config import Settings, get_settings
from app.db.models import Message, SenderType

logger = logging.getLogger(__name__)

HANDOFF_FLAG = "[REQUIRES_HUMAN]"
_HANDOFF_PATTERN = re.compile(r"\[REQUIRES_HUMAN\]", re.IGNORECASE)

_FALLBACK_MODELS = ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash")


@dataclass(slots=True)
class AIReply:
    text: str
    requires_human: bool
    raw_text: str
    error: bool = False


class AIEngineError(RuntimeError):
    """Raised when Gemini cannot produce a reply after retries."""


def parse_llm_output(raw_text: str) -> AIReply:
    """Extract the handoff flag and a customer-safe reply body."""
    requires_human = bool(_HANDOFF_PATTERN.search(raw_text or ""))
    cleaned = _HANDOFF_PATTERN.sub("", raw_text or "").strip()
    return AIReply(text=cleaned, requires_human=requires_human, raw_text=raw_text or "")


class AIEngine:
    """Thin wrapper around `google.genai.Client` used by webhook processing."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from google.genai import Client

            if not self.settings.gemini_api_key:
                raise AIEngineError("GEMINI_API_KEY is not configured")
            self._client = Client(api_key=self.settings.gemini_api_key)
        return self._client

    def generate_reply(self, history: Sequence[Message], user_text: str) -> AIReply:
        """Call Gemini with prior SQLite messages as `contents` and parse the result."""
        contents = self.build_contents(history, user_text)
        try:
            raw = self._generate_content(contents)
        except Exception:
            logger.exception("Gemini generation failed; escalating to human handoff")
            return AIReply(
                text="",
                requires_human=True,
                raw_text="",
                error=True,
            )
        return parse_llm_output(raw)

    def build_contents(self, history: Sequence[Message], user_text: str) -> list[dict[str, Any]]:
        """Map stored messages to the google-genai `contents` payload."""
        contents: list[dict[str, Any]] = []
        for message in history:
            role = "user" if message.sender_type == SenderType.USER else "model"
            text = message.text
            if message.sender_type == SenderType.HUMAN_AGENT:
                text = f"[Human agent]: {text}"
            contents.append({"role": role, "parts": [{"text": text}]})

        if not contents or contents[-1].get("role") != "user" or _last_text(contents) != user_text:
            contents.append({"role": "user", "parts": [{"text": user_text}]})
        return contents

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_none(),
        retry=retry_if_exception_type(Exception),
    )
    def _generate_content(self, contents: list[dict[str, Any]]) -> str:
        models_to_try = _unique_models(self.settings.gemini_model)
        last_error: Exception | None = None
        for model_name in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config={
                        "system_instruction": self.settings.bot_system_instruction,
                        "temperature": 0.4,
                    },
                )
                text = _extract_text(response)
                if text:
                    if model_name != self.settings.gemini_model:
                        logger.warning("Fell back to Gemini model %s", model_name)
                    return text
                last_error = AIEngineError("Gemini returned an empty response")
            except Exception as exc:  # noqa: BLE001 - SDK raises multiple types
                last_error = exc
                logger.warning("Gemini model %s failed: %s", model_name, exc)
        raise last_error or AIEngineError("Gemini returned an empty response")


def _unique_models(preferred: str) -> list[str]:
    ordered = [preferred, *_FALLBACK_MODELS]
    seen: set[str] = set()
    result: list[str] = []
    for name in ordered:
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _last_text(contents: list[dict[str, Any]]) -> str:
    parts = contents[-1].get("parts") or []
    if not parts:
        return ""
    return str(parts[0].get("text") or "")


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        chunks = [getattr(part, "text", "") for part in parts if getattr(part, "text", "")]
        if chunks:
            return "\n".join(chunks).strip()
    return ""
