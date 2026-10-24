from app.kb.corpus import articles
from app.kb.ingest import ingest_directory, parse_html, parse_markdown, write_corpus


def test_corpus_has_about_thirty_articles():
    rows = articles()
    kinds = {row["kind"] for row in rows}
    assert len(rows) >= 30
    assert {"md", "html", "pdf"} <= kinds


def test_markdown_html_and_pdf_round_trip(tmp_path):
    write_corpus(tmp_path)
    markdown = (tmp_path / "cancel-order.md").read_text(encoding="utf-8")
    title, article_id, sections, _body = parse_markdown(markdown)
    assert article_id == "cancel-order"
    assert title == "Cancelling an order"
    assert any("24 hours" in text for _name, text in sections)

    html_title, html_id, html_sections, _html = parse_html((tmp_path / "gift-cards.html").read_text(encoding="utf-8"), "gift-cards")
    assert html_id == "gift-cards"
    assert html_title == "Gift cards"
    assert any("do not expire" in text for _name, text in html_sections)

    from app.db import configure, init_schema, session

    configure(f"sqlite:///{tmp_path}/ingest.db")
    init_schema()
    db = session()
    count = ingest_directory(db, tmp_path)
    assert count >= 30
    from app.models import Article, Chunk
    from sqlalchemy import select

    holiday = db.get(Article, "holiday-cutoff")
    assert holiday is not None
    assert holiday.source_type == "pdf"
    chunks = db.scalars(select(Chunk).where(Chunk.article_id == "holiday-cutoff")).all()
    assert any("December 16" in chunk.text for chunk in chunks)
    gift = db.get(Article, "gift-cards")
    assert gift.source_type == "html"
    db.close()
