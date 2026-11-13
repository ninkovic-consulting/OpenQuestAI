"""Tiny files for the library's tests, built in memory: a PDF with text, a PDF of
blank pages (as a scan looks to a text reader), and a Word document."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape


def pdf_with(*pages: str) -> bytes:
    """A valid PDF, one page per string, each line drawn in Helvetica."""
    objects: list[bytes] = []
    count = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode())
    font = 3 + 2 * count
    for i, text in enumerate(pages):
        lines = []
        for n, line in enumerate(text.split("\n")):
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"BT /F1 12 Tf 72 {720 - 16 * n} Td ({safe}) Tj ET")
        stream = "\n".join(lines).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    return _assemble(objects)


def blank_pdf(pages: int = 2) -> bytes:
    """A PDF whose pages hold no text, like scanned pages without a text layer."""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + i} 0 R" for i in range(pages))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    objects += [b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"] * pages
    return _assemble(objects)


def _assemble(objects: list[bytes]) -> bytes:
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % n + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def docx_with(*paragraphs: str) -> bytes:
    """A minimal Word document: one paragraph per string; a tab inside one is a `w:tab`."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = []
    for text in paragraphs:
        runs = "<w:r><w:tab/></w:r>".join(f'<w:r><w:t xml:space="preserve">{escape(part)}</w:t></w:r>' for part in text.split("\t"))
        body.append(f"<w:p>{runs}</w:p>")
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{ns}"><w:body>{"".join(body)}</w:body></w:document>'
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", document)
    return out.getvalue()
