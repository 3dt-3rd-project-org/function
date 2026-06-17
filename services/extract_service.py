import json
import time
import logging

from services.openai_service import extract_chapter_analysis
from services.db_service import add_llm_usage


def is_content_filter_error(error: Exception) -> bool:
    error_text = str(error)

    return (
        "content_filter" in error_text
        or "ResponsibleAIPolicyViolation" in error_text
    )


def save_filtered_chapter(
    cur,
    books_id: int,
    chapter_id: int,
    chapter_order: int,
    chapter_title: str
):
    empty_result = {
        "characters": [],
        "events": [],
        "relationships": []
    }

    cur.execute(
        """
        INSERT INTO chapter_analysis_raw (
            books_id,
            chapter_id,
            chapter_order,
            chapter_title,
            raw_json,
            status,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s::jsonb, 'FILTERED', CURRENT_TIMESTAMP)
        ON CONFLICT (books_id, chapter_id)
        DO UPDATE SET
            chapter_order = EXCLUDED.chapter_order,
            chapter_title = EXCLUDED.chapter_title,
            raw_json = EXCLUDED.raw_json,
            status = 'FILTERED',
            updated_at = CURRENT_TIMESTAMP;
        """,
        (
            books_id,
            chapter_id,
            chapter_order,
            chapter_title,
            json.dumps(empty_result, ensure_ascii=False)
        )
    )


def run_openai_extract_chapter(conn, books_id: int, chapter_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT chapter_id, chapter_order, title
            FROM chapter
            WHERE books_id = %s
              AND chapter_id = %s;
            """,
            (books_id, chapter_id)
        )

        chapter = cur.fetchone()

        if not chapter:
            return {"error": "chapter not found"}

        chapter_id, chapter_order, chapter_title = chapter

        cur.execute(
            """
            SELECT paragraph_id,
                   paragraph_order,
                   content
            FROM paragraph
            WHERE books_id = %s
              AND chapter_id = %s
            ORDER BY paragraph_order;
            """,
            (books_id, chapter_id)
        )

        paragraphs = cur.fetchall()

        if not paragraphs:
            return {"error": "paragraph not found"}

        chapter_text = "\n".join(
            [f"[문단 {p[1]}] {p[2]}" for p in paragraphs]
        )

        logging.info(
            "openai_extract_chapter start. books_id=%s, chapter_id=%s, paragraph_count=%s",
            books_id,
            chapter_id,
            len(paragraphs)
        )

        max_retries = 2
        last_error = None
        result = None

        for attempt in range(1, max_retries + 1):
            try:
                logging.info(
                    "calling GPT. books_id=%s, chapter_id=%s, attempt=%s/%s",
                    books_id,
                    chapter_id,
                    attempt,
                    max_retries
                )

                openai_result = extract_chapter_analysis(
                    chapter_title=chapter_title,
                    chapter_text=chapter_text
                )

                result = openai_result["data"]
                usage = openai_result["usage"]

                add_llm_usage(
                    conn=conn,
                    books_id=books_id,
                    prompt_tokens=usage["prompt_tokens"],
                    completion_tokens=usage["completion_tokens"],
                    total_tokens=usage["total_tokens"]
                )

                break

            except Exception as e:
                last_error = e

                logging.exception(
                    "GPT extract failed. books_id=%s, chapter_id=%s, attempt=%s/%s",
                    books_id,
                    chapter_id,
                    attempt,
                    max_retries
                )

                if is_content_filter_error(e):
                    logging.warning(
                        "Content filter detected. Stop retry and save as FILTERED. books_id=%s, chapter_id=%s",
                        books_id,
                        chapter_id
                    )
                    break

                if attempt < max_retries:
                    time.sleep(2)

        if result is None:
            if is_content_filter_error(last_error):
                save_filtered_chapter(
                    cur=cur,
                    books_id=books_id,
                    chapter_id=chapter_id,
                    chapter_order=chapter_order,
                    chapter_title=chapter_title
                )

                conn.commit()

                return {
                    "status": "filtered",
                    "message": "chapter skipped by Azure OpenAI content filter",
                    "books_id": books_id,
                    "chapter_id": chapter_id,
                    "chapter_order": chapter_order,
                    "chapter_title": chapter_title,
                    "character_count": 0,
                    "event_count": 0,
                    "relationship_count": 0
                }

            raise last_error

        cur.execute(
            """
            INSERT INTO chapter_analysis_raw (
                books_id,
                chapter_id,
                chapter_order,
                chapter_title,
                raw_json,
                status,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, 'RAW', CURRENT_TIMESTAMP)
            ON CONFLICT (books_id, chapter_id)
            DO UPDATE SET
                chapter_order = EXCLUDED.chapter_order,
                chapter_title = EXCLUDED.chapter_title,
                raw_json = EXCLUDED.raw_json,
                status = 'RAW',
                updated_at = CURRENT_TIMESTAMP;
            """,
            (
                books_id,
                chapter_id,
                chapter_order,
                chapter_title,
                json.dumps(result, ensure_ascii=False)
            )
        )

        conn.commit()

        return {
            "status": "success",
            "message": "chapter raw analysis saved",
            "books_id": books_id,
            "chapter_id": chapter_id,
            "chapter_order": chapter_order,
            "chapter_title": chapter_title,
            "character_count": len(result.get("characters", [])),
            "event_count": len(result.get("events", [])),
            "relationship_count": len(result.get("relationships", [])),
        }