"""Unit tests for Gemini output parsing and conversational contents mapping."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config import Settings
from app.db.models import Message, SenderType
from app.services.ai_engine import AIEngine, HANDOFF_FLAG, parse_llm_output


def _message(sender: SenderType, text: str, message_id: int = 1) -> Message:
    return Message(
        id=message_id,
        conversation_id=1,
        sender_type=sender,
        text=text,
        timestamp=datetime.now(timezone.utc),
    )


def test_parse_llm_output_faq_without_handoff():
    result = parse_llm_output("Our refund window is 30 days.")
    assert result.requires_human is False
    assert result.text == "Our refund window is 30 days."


def test_parse_llm_output_detects_requires_human_flag():
    result = parse_llm_output(f"{HANDOFF_FLAG} Customer is asking for a refund.")
    assert result.requires_human is True
    assert HANDOFF_FLAG not in result.text
    assert "refund" in result.text.lower()


def test_parse_llm_output_is_case_insensitive():
    result = parse_llm_output("[requires_human] User is furious.")
    assert result.requires_human is True
    assert result.text == "User is furious."


def test_generate_reply_faq_uses_mock_gemini_client():
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(
        text="We ship worldwide. Delivery takes 3–5 business days."
    )
    engine = AIEngine(
        settings=Settings(gemini_api_key="test-key", gemini_model="gemini-3.6-flash"),
        client=client,
    )
    reply = engine.generate_reply([], "Do you ship internationally?")
    assert reply.requires_human is False
    assert "ship" in reply.text.lower()
    client.models.generate_content.assert_called_once()
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3.6-flash"
    assert kwargs["contents"][-1]["role"] == "user"
    assert "ship" in kwargs["contents"][-1]["parts"][0]["text"].lower()
    assert "system_instruction" in kwargs["config"]


def test_generate_reply_triggers_human_handoff():
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(
        text=f"{HANDOFF_FLAG} Refund request should be handled by an agent."
    )
    engine = AIEngine(settings=Settings(gemini_api_key="test-key"), client=client)
    reply = engine.generate_reply([], "I want a refund now, this is unacceptable!")
    assert reply.requires_human is True
    assert "Refund request" in reply.text


def test_build_contents_includes_sqlite_history():
    engine = AIEngine(settings=Settings(gemini_api_key="test-key"), client=MagicMock())
    history = [
        _message(SenderType.USER, "Hello", 1),
        _message(SenderType.BOT, "Hi! How can I help?", 2),
        _message(SenderType.HUMAN_AGENT, "I'll take it from here.", 3),
    ]
    contents = engine.build_contents(history, "Can I speak to someone?")
    assert contents[0] == {"role": "user", "parts": [{"text": "Hello"}]}
    assert contents[1] == {"role": "model", "parts": [{"text": "Hi! How can I help?"}]}
    assert contents[2]["role"] == "model"
    assert contents[2]["parts"][0]["text"].startswith("[Human agent]:")
    assert contents[-1]["parts"][0]["text"] == "Can I speak to someone?"


def test_gemini_failure_escalates_to_human():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("quota exceeded")
    engine = AIEngine(settings=Settings(gemini_api_key="test-key"), client=client)
    reply = engine.generate_reply([], "Hello")
    assert reply.requires_human is True
    assert reply.error is True
    assert reply.text == ""
