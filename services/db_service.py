import os
import psycopg2


def get_conn():
    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        sslmode="require"
    )


def get_book_by_id(conn, books_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT books_id, title, author, epub_blob_path
            FROM books
            WHERE books_id = %s;
            """,
            (books_id,)
        )
        return cur.fetchone()


def save_chapters_and_paragraphs(conn, books_id: int, rows: list[dict]):
    with conn.cursor() as cur:
        chapter_map = {}

        # 기존 데이터 삭제 후 재적재
        cur.execute("DELETE FROM paragraph WHERE books_id = %s;", (books_id,))
        cur.execute("DELETE FROM chapter WHERE books_id = %s;", (books_id,))

        # chapter 저장
        seen_chapters = {}
        for row in rows:
            chapter_order = int(row["chapter_order"])

            if chapter_order not in seen_chapters:
                seen_chapters[chapter_order] = row["chapter_title"]

        for chapter_order, chapter_title in sorted(seen_chapters.items()):
            cur.execute(
                """
                INSERT INTO chapter (books_id, chapter_order, title)
                VALUES (%s, %s, %s)
                RETURNING chapter_id;
                """,
                (books_id, chapter_order, chapter_title)
            )
            chapter_id = cur.fetchone()[0]
            chapter_map[chapter_order] = chapter_id

        # paragraph 저장
        for row in rows:
            chapter_order = int(row["chapter_order"])
            chapter_id = chapter_map[chapter_order]

            cur.execute(
                """
                INSERT INTO paragraph (
                    books_id,
                    chapter_id,
                    paragraph_order,
                    epub_href,
                    content
                )
                VALUES (%s, %s, %s, %s, %s);
                """,
                (
                    books_id,
                    chapter_id,
                    int(row["paragraph_order"]),
                    row["epub_href"],
                    row["content"]
                )
            )

        return {
            "chapter_count": len(chapter_map),
            "paragraph_count": len(rows)
        }