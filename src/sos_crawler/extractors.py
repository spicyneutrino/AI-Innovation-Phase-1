import io
import re

import pdfplumber
from lxml import html as lxml_html


def extract_pdf_text(pdf_bytes: bytes, max_chars: int = 50000) -> str:
    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text() or ""
                if txt:
                    text_parts.append(txt)
        text = "\n".join(text_parts).strip()
        return text[:max_chars]
    except Exception:
        return ""


def clean_text(text: str, max_chars: int = 50000, preserve_newlines: bool = False) -> str:
    text = (text or "").replace("\xa0", " ")
    if preserve_newlines:
        lines = []
        for raw_line in re.split(r"[\r\n]+", text):
            line = re.sub(r"\s+", " ", raw_line).strip()
            if line:
                lines.append(line)
        text = "\n".join(lines)
    else:
        text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _drop_boilerplate(tree) -> None:
    for bad in tree.xpath("//script|//style|//noscript|//svg|//form|//nav|//footer|//header|//aside"):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)


def _extract_from_tree(tree, max_chars: int = 50000) -> str:
    _drop_boilerplate(tree)
    candidate_xpaths = [
        "//main",
        "//article",
        "//*[@role='main']",
        "//*[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'content')]",
        "//*[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'main')]",
        "//*[contains(translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'article')]",
    ]

    text_chunks = []
    seen = set()
    for xpath in candidate_xpaths:
        for node in tree.xpath(xpath):
            chunk = clean_text("\n".join(node.xpath(".//text()")), max_chars=max_chars, preserve_newlines=True)
            if chunk and chunk not in seen:
                text_chunks.append(chunk)
                seen.add(chunk)
        if text_chunks:
            break

    if not text_chunks:
        body_nodes = tree.xpath("//body") or [tree]
        for node in body_nodes:
            chunk = clean_text("\n".join(node.xpath(".//text()")), max_chars=max_chars, preserve_newlines=True)
            if chunk:
                text_chunks.append(chunk)

    text = "\n\n".join(text_chunks)
    return clean_text(text, max_chars=max_chars, preserve_newlines=True)


def extract_html_text(response, max_chars: int = 50000) -> str:
    try:
        tree = response.selector.root
        return _extract_from_tree(tree, max_chars=max_chars)
    except Exception:
        try:
            return extract_html_text_from_bytes(response.body, max_chars=max_chars)
        except Exception:
            return ""


def extract_html_text_from_bytes(html_bytes: bytes, max_chars: int = 50000) -> str:
    try:
        tree = lxml_html.fromstring(html_bytes or b"")
        return _extract_from_tree(tree, max_chars=max_chars)
    except Exception:
        return ""
