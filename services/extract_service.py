import json

from services.openai_service import extract_chapter_analysis


def run_openai_extract(conn, books_id: int):

    with conn.cursor() as cur:

        # 챕터 목록 조회
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
            return {
                "error": "chapter not found"
            }

        # 첫 챕터만 테스트
        chapters = chapters[2:3]

        all_results = []

        for chapter_id, chapter_order, chapter_title in chapters:

            print("\n" + "=" * 80)
            print(f"CHAPTER START : {chapter_title}")
            print("=" * 80)

            # 문단 조회
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

            print(
                f"Paragraph Count : {len(paragraphs)}"
            )

            print("Calling GPT...")

            result = extract_chapter_analysis(
                chapter_title=chapter_title,
                chapter_text=chapter_text
            )

            print("GPT Done")

            print("\n")
            print("=" * 80)
            print("GPT RESULT")
            print("=" * 80)

            print(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    indent=2
                )
            )

            print("=" * 80)
            print("\n")

            all_results.append(
                {
                    "chapter_id": chapter_id,
                    "chapter_title": chapter_title,
                    "result": result
                }
            )

        return {
            "status": "success",
            "books_id": books_id,
            "chapter_count": len(all_results),
            "results": all_results
        }