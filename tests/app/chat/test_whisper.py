from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from app.chat.media import media_to_part


def make_audio_upload(content: bytes, mime: str, filename: str) -> UploadFile:
    mock = MagicMock(spec=UploadFile)
    mock.content_type = mime
    mock.filename = filename
    mock.size = len(content)
    mock.read = AsyncMock(return_value=content)
    return mock


@pytest.mark.asyncio
async def test_voice_returns_text_part_with_prefix():
    fake_audio = b"OggS" + b"\x00" * 50
    upload = make_audio_upload(fake_audio, "audio/ogg", "voice.ogg")

    llm = MagicMock()
    transcript_result = MagicMock()
    transcript_result.text = "Привет, как дела?"
    llm.audio = MagicMock()
    llm.audio.transcriptions = MagicMock()
    llm.audio.transcriptions.create = AsyncMock(return_value=transcript_result)

    part = await media_to_part(upload, llm)

    assert part["type"] == "text"
    assert part["text"].startswith("[пользователь сказал голосом]:")
    assert "Привет, как дела?" in part["text"]