"""`rogue setup` — the one-command opt-in installer for the best free scraper (crawl4ai + browser)."""

from __future__ import annotations

from rogue.cli import main


def test_setup_dry_run_installs_crawl4ai_and_browser(capsys):
    rc = main(["setup", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "pip install crawl4ai" in out
    assert "chromium" in out  # browser download step
    assert "pymupdf4llm" not in out  # not unless --pdf


def test_setup_pdf_adds_pymupdf4llm(capsys):
    main(["setup", "--pdf", "--dry-run"])
    out = capsys.readouterr().out
    assert "crawl4ai" in out
    assert "pymupdf4llm" in out


def test_setup_no_browser_skips_chromium(capsys):
    main(["setup", "--no-browser", "--dry-run"])
    out = capsys.readouterr().out
    assert "crawl4ai" in out
    assert "chromium" not in out
