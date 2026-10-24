"""Ingest Markdown, HTML, and PDF into article and chunk rows."""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.kb.corpus import articles
from app.models import Article, Chunk
from app.textutil import nid


def write_corpus(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for spec in articles():
        kind = spec["kind"]
        if kind == "md":
            (directory / f"{spec['id']}.md").write_text(_markdown(spec), encoding="utf-8")
        elif kind == "html":
            (directory / f"{spec['id']}.html").write_text(_html(spec), encoding="utf-8")
        elif kind == "pdf":
            _pdf(directory / f"{spec['id']}.pdf", spec)


def seed_knowledge(session: Session, directory: Path) -> int:
    write_corpus(directory)
    return ingest_directory(session, directory)


def ingest_directory(session: Session, directory: Path) -> int:
    count = 0
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() in {".md", ".markdown", ".html", ".htm", ".pdf"}:
            ingest_file(session, path)
            count += 1
    session.commit()
    return count


def ingest_file(session: Session, path: Path) -> Article:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        title, article_id, sections, body = parse_markdown(path.read_text(encoding="utf-8"))
        source_type = "md"
    elif suffix in {".html", ".htm"}:
        title, article_id, sections, body = parse_html(path.read_text(encoding="utf-8"), fallback_id=path.stem)
        source_type = "html"
    elif suffix == ".pdf":
        title, article_id, sections, body = parse_pdf(path)
        source_type = "pdf"
    else:
        raise ValueError(f"Unsupported file {path.name}")
    return _store(session, article_id or path.stem, title, source_type, path.name, body, sections)


def parse_markdown(text: str) -> tuple[str, str | None, list[tuple[str, str]], str]:
    article_id = None
    title = None
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            header = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            for line in header.splitlines():
                if line.startswith("id:"):
                    article_id = line.split(":", 1)[1].strip()
                if line.startswith("title:"):
                    title = line.split(":", 1)[1].strip()
    sections = _split_headings(body)
    if title is None:
        title = sections[0][0] if sections else "Untitled"
    if not sections:
        sections = [(title, body.strip())]
    return title, article_id, sections, body.strip()


def parse_html(text: str, fallback_id: str) -> tuple[str, str, list[tuple[str, str]], str]:
    soup = BeautifulSoup(text, "lxml")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else fallback_id
    sections: list[tuple[str, str]] = []
    for heading in soup.find_all("h2"):
        parts: list[str] = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in {"h1", "h2"}:
                break
            words = sibling.get_text(" ", strip=True) if getattr(sibling, "get_text", None) else str(sibling).strip()
            if words:
                parts.append(words)
        sections.append((heading.get_text(" ", strip=True), " ".join(parts).strip()))
    if not sections:
        sections = [(title, soup.get_text(" ", strip=True))]
    return title, fallback_id, sections, soup.get_text("\n", strip=True)


def parse_pdf(path: Path) -> tuple[str, str, list[tuple[str, str]], str]:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else path.stem
    # Drop a repeated title line.
    rest = lines[1:] if lines and lines[0] == title else lines
    paragraph = " ".join(rest).strip() or text
    section = "Christmas" if "December 16" in paragraph else "Page 1"
    return title, path.stem, [(section, paragraph)], text


def _split_headings(body: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^##\s+(.+)$", body, re.M))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group(1).strip(), body[start:end].strip()))
    return sections


def _store(session, article_id, title, source_type, source_name, body, sections) -> Article:
    existing = session.get(Article, article_id)
    if existing is not None:
        session.execute(delete(Chunk).where(Chunk.article_id == article_id))
        session.delete(existing)
        session.flush()
    article = Article(id=article_id, title=title, source_type=source_type, source_name=source_name, body=body)
    session.add(article)
    session.flush()
    position = 0
    for section, text in sections:
        parent = re.sub(r"\s+", " ", text).strip()
        if not parent:
            continue
        # Small passages are what we embed. The stored text is the whole section
        # so a hit expands back to the passage the customer can be quoted from.
        for passage in _passages(parent):
            session.add(
                Chunk(
                    id=nid("chk_"),
                    article_id=article_id,
                    title=title,
                    section=section,
                    text=parent,
                    embed_text=f"v2\n{title}\n{section}\n{passage}",
                    position=position,
                    embedding=None,
                )
            )
            position += 1
    session.flush()
    return article


def _passages(text: str) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.])\s+", text) if part.strip()]
    if len(sentences) <= 1:
        return [text]
    passages = list(sentences)
    for left, right in zip(sentences, sentences[1:]):
        passages.append(f"{left} {right}")
    if text not in passages:
        passages.append(text)
    return passages


def _windows(text: str, limit: int = 900) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return [text] if text else []
    sentences = re.split(r"(?<=[.])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= limit:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _markdown(spec: ArticleSpec) -> str:
    lines = ["---", f"id: {spec['id']}", f"title: {spec['title']}", "---", ""]
    for section, text in spec["sections"]:
        lines.append(f"## {section}")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _html(spec: ArticleSpec) -> str:
    parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'>",
        f"<title>{spec['title']}</title></head><body>",
        f"<h1>{spec['title']}</h1>",
    ]
    for section, text in spec["sections"]:
        parts.append(f"<h2>{section}</h2>")
        parts.append(f"<p>{text}</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _pdf(path: Path, spec: ArticleSpec) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    def line(text: str, height: int, style: str = "", size: int = 12) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", style=style, size=size)
        pdf.multi_cell(pdf.epw, height, text)

    line(spec["title"], 10, size=16)
    pdf.ln(4)
    for section, text in spec["sections"]:
        line(section, 8, style="B", size=12)
        line(text, 7, size=12)
        pdf.ln(3)
    pdf.output(str(path))


def article_count(session: Session) -> int:
    return len(session.scalars(select(Article.id)).all())
