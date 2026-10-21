"""Reading the printed text on a DVR label.

The device ID is printed on these labels but never barcoded - the barcode under
it carries the serial number instead - so the only way to pick it up from a
photo is to read the print. Windows has an OCR engine built in, so this needs
nothing installed on the server beyond the Python bindings for it.

Everything here answers with an empty string rather than raising: a label whose
print cannot be read still has its barcodes, and the operator can type the rest.
"""

from __future__ import annotations

import asyncio
import io
import logging

logger = logging.getLogger("tacho.labels")


async def _recognise(data: bytes) -> str:
    from PIL import Image, ImageOps
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="BMP")

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream.get_output_stream_at(0))
    writer.write_bytes(buffer.getvalue())
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        logger.warning("Windows has no OCR language installed, so label print cannot be read")
        return ""
    return (await engine.recognize_async(bitmap)).text or ""


def read_text(data: bytes) -> str:
    """Every word the engine can find in the photo, as one string."""
    try:
        return asyncio.run(_recognise(data))
    except Exception:  # noqa: BLE001 - a label that will not read is answered, not raised
        logger.exception("could not read the print on a label photo")
        return ""
