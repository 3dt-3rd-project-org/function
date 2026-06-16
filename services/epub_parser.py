from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
import re


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_body_section(item_name: str) -> bool:
    name = item_name.lower()

    # 표지, 라이선스, 목차 제외
    exclude_patterns = [
        "cover",
        "license",
        "nav",
        "toc",
        "title",
    ]

    if any(x in name for x in exclude_patterns):
        return False

    # 본문 파일 패턴 허용
    return bool(
        re.search(r"(section|chap|chapter)\d+\.x?html$", name)
    )


def parse_epub(epub_path: str):
    book = epub.read_epub(epub_path)

    rows = []
    chapter_order = 0

    for item_id, _ in book.spine:
        item = book.get_item_with_id(item_id)

        if item is None:
            continue

        if item.get_type() != ITEM_DOCUMENT:
            continue

        item_name = item.get_name()

        if not is_body_section(item_name):
            continue

        soup = BeautifulSoup(item.get_content(), "xml")

        paragraphs = []

        for p in soup.find_all("p"):
            text = clean_text(p.get_text())

            if len(text) >= 10:
                paragraphs.append(text)

        if not paragraphs:
            continue

        chapter_order += 1

        title_tag = soup.find(["h1", "h2", "h3"])
        chapter_title = clean_text(title_tag.get_text()) if title_tag else f"chapter_{chapter_order}"

        if chapter_order == 1 and chapter_title == "chapter_1":
            chapter_order -= 1
            continue

        for paragraph_order, content in enumerate(paragraphs, start=1):
            rows.append({
                "chapter_order": chapter_order,
                "chapter_title": chapter_title,
                "paragraph_order": paragraph_order,
                "epub_href": item_name,
                "content": content
            })

    return rows