import json

from services.openai_service import extract_chapter_analysis


def run_openai_extract(conn, books_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT chapter_id, chapter_order, title
            FROM chapter
            WHERE books_id = %s
            ORDER BY chapter_order;
            """,
            (books_id,)
        )

        chapters = cur.fetchall()

        if not chapters:
            return {"error": "chapter not found"}

        all_results = []

        for chapter_id, chapter_order, chapter_title in chapters:
            print("\n" + "=" * 80)
            print(f"CHAPTER START : {chapter_title}")
            print("=" * 80)

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
                continue

            chapter_text = "\n".join(
                [
                    f"[문단 {p[1]}] {p[2]}"
                    for p in paragraphs
                ]
            )

            print(f"Paragraph Count : {len(paragraphs)}")
            print("Calling GPT...")

            result = extract_chapter_analysis(
                chapter_title=chapter_title,
                chapter_text=chapter_text
            )

            print("GPT Done")
            print(json.dumps(result, ensure_ascii=False, indent=2))

            # =========================
            # Raw JSON 저장
            # =========================
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

            all_results.append(
                {
                    "chapter_id": chapter_id,
                    "chapter_order": chapter_order,
                    "chapter_title": chapter_title,
                    "character_count": len(result.get("characters", [])),
                    "event_count": len(result.get("events", [])),
                    "relationship_count": len(result.get("relationships", [])),
                    "status": "RAW_SAVED"
                }
            )

        return {
            "status": "success",
            "message": "chapter raw analysis saved",
            "books_id": books_id,
            "chapter_count": len(all_results),
            "results": all_results
        }