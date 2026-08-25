import base64
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from app.chat.media import media_to_part


def make_upload(content: bytes, content_type: str, filename: str = "file") -> UploadFile:
    mock = MagicMock(spec=UploadFile)
    mock.content_type = content_type
    mock.filename = filename
    mock.size = len(content)
    mock.read = AsyncMock(return_value=content)
    return mock


@pytest.mark.asyncio
async def test_image_returns_image_url_part():
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    upload = make_upload(png_bytes, "image/png", "photo.png")
    llm = MagicMock()

    part = await media_to_part(upload, llm)

    assert part["type"] == "image_url"
    url = part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    decoded = base64.b64decode(url.split(",", 1)[1])
    assert decoded == png_bytes


@pytest.mark.asyncio
async def test_pdf_returns_text_part(tmp_path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    upload = make_upload(pdf_bytes, "application/pdf", "doc.pdf")
    llm = MagicMock()

    part = await media_to_part(upload, llm)

    assert part["type"] == "text"
    assert part["text"].startswith("[документ PDF]:")