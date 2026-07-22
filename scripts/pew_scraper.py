#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
#     "lxml",
# ]
# ///
"""
pew_scraper.py -- Download Pew Research Center report PDFs (+ metadata) for
downstream use (e.g. RAG ingestion).

Crawls a Pew "topic" or category listing page (paginated via /page/N/),
finds individual publication pages, and for each one that matches the
requested --formats, downloads its "Report Materials" PDFs (report, topline,
questionnaire, etc.) plus a metadata.jsonl sidecar record.

Usage:
    uv run pew_scraper.py \\
        --topic-url https://www.pewresearch.org/topic/international-affairs/ \\
        --out ./pew_reports --max-pages 20 --formats report

Etiquette / compliance:
    - Only touches public, unauthenticated pages/PDFs -- no login bypass.
    - Check https://www.pewresearch.org/robots.txt and
      https://www.pewresearch.org/about/terms-and-conditions/ before running
      this at scale, and keep the delay reasonable (default: 1 req/sec).
    - Set --contact-email so your User-Agent identifies you, in case Pew's
      admins ever want to reach out about crawl behavior.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ARTICLE_URL_RE = re.compile(
    r"https://www\.pewresearch\.org/[a-z\-]+/\d{4}/\d{2}/\d{2}/[^\"'#?]+/?$"
)


def fetch(session, url, **kwargs):
    resp = session.get(url, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp


def listing_page_url(topic_url, page_num):
    topic_url = topic_url.rstrip("/")
    if page_num == 1:
        return topic_url + "/"
    return f"{topic_url}/page/{page_num}/"


def extract_article_links(html, base_url):
    """Pull individual publication-page URLs out of a listing page.

    Matches on the /<section>/YYYY/MM/DD/slug/ URL shape Pew uses for every
    publication type (global, short-reads, internet, politics, ...), rather
    than relying on CSS classes that can change with site redesigns.
    """
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if ARTICLE_URL_RE.match(href):
            links.add(href.split("?")[0].split("#")[0])
    return links


def parse_article(session, url):
    """Return (metadata dict, list of pdf urls) for a single publication page."""
    resp = fetch(session, url)
    soup = BeautifulSoup(resp.text, "lxml")

    def meta(name):
        tag = soup.find("meta", attrs={"name": name}) or soup.find(
            "meta", attrs={"property": name}
        )
        return tag["content"].strip() if tag and tag.get("content") else None

    title = meta("og:title") or (soup.title.string.strip() if soup.title else url)
    published = meta("article:published_time")
    tags = meta("parsely-tags") or ""
    fmt_match = re.search(r"format__([a-z\-]+)", tags)
    fmt = fmt_match.group(1) if fmt_match else "unknown"

    authors = [a.get_text(strip=True) for a in soup.select("a[href*='/staff/']")]

    pdf_urls = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if href.lower().endswith(".pdf") and "wp-content/uploads" in href:
            pdf_urls.add(href)

    metadata = {
        "url": url,
        "title": title,
        "published": published,
        "format": fmt,
        "authors": authors,
        "pdfs": sorted(pdf_urls),
    }
    return metadata, sorted(pdf_urls)


def download_pdf(session, pdf_url, dest_dir, delay):
    fname = Path(urlparse(pdf_url).path).name
    dest = dest_dir / fname
    if dest.exists():
        return dest, False
    resp = fetch(session, pdf_url, stream=True)
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    time.sleep(delay)
    return dest, True


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--topic-url", required=True, help="Pew topic/category listing URL")
    ap.add_argument("--out", default="./pew_reports", help="Output directory")
    ap.add_argument("--max-pages", type=int, default=10, help="Listing pages to crawl")
    ap.add_argument(
        "--formats",
        nargs="*",
        default=["report"],
        help="Formats to keep, e.g. report data-essay feature fact-sheet",
    )
    ap.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    ap.add_argument(
        "--contact-email",
        default="",
        help="Included in the User-Agent string so the crawl is identifiable",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    pdf_dir = out_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "metadata.jsonl"

    ua = "PewResearchArchiver/1.0 (personal research project"
    ua += f"; contact: {args.contact_email})" if args.contact_email else ")"

    session = requests.Session()
    session.headers["User-Agent"] = ua

    all_article_urls = set()
    for page_num in range(1, args.max_pages + 1):
        list_url = listing_page_url(args.topic_url, page_num)
        print(f"[listing] page {page_num}: {list_url}", file=sys.stderr)
        try:
            resp = fetch(session, list_url)
        except requests.HTTPError as e:
            print(f"  stopping, got {e}", file=sys.stderr)
            break
        links = extract_article_links(resp.text, list_url)
        if not links:
            print("  no article links found, stopping", file=sys.stderr)
            break
        all_article_urls |= links
        time.sleep(args.delay)

    print(f"Found {len(all_article_urls)} candidate article pages", file=sys.stderr)

    kept = 0
    seen_pdfs = set()
    with open(meta_path, "a", encoding="utf-8") as meta_f:
        for url in sorted(all_article_urls):
            try:
                print(f"Parsing: {url}", file=sys.stderr)
                metadata, pdf_urls = parse_article(session, url)
            except requests.RequestException as e:
                print(f"  [skip] {url}: connection/timeout error: {e}", file=sys.stderr)
                continue

            if metadata["format"] not in args.formats:
                continue
            if not pdf_urls:
                continue
            # Multi-chapter reports repeat the same PDF links on every
            # chapter page -- skip once we've already recorded this exact
            # set of PDFs so metadata.jsonl has one row per report, not
            # one per chapter.
            pdf_key = tuple(pdf_urls)
            if pdf_key in seen_pdfs:
                continue
            seen_pdfs.add(pdf_key)

            kept += 1
            local_paths = []
            for pdf_url in pdf_urls:
                try:
                    dest, downloaded = download_pdf(session, pdf_url, pdf_dir, args.delay)
                    local_paths.append(str(dest))
                    tag = "downloaded" if downloaded else "cached"
                    print(f"  [{tag}] {dest.name}", file=sys.stderr)
                except requests.HTTPError as e:
                    print(f"  [pdf-fail] {pdf_url}: {e}", file=sys.stderr)

            metadata["local_pdfs"] = local_paths
            meta_f.write(json.dumps(metadata, ensure_ascii=False) + "\n")
            time.sleep(args.delay)

    print(f"Done. Kept {kept} publications matching formats {args.formats}.", file=sys.stderr)
    print(f"PDFs in:    {pdf_dir}", file=sys.stderr)
    print(f"Metadata:   {meta_path}", file=sys.stderr)


if __name__ == "__main__":
    main()