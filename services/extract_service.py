import json

from services.openai_service import extract_chapter_analysis, get_three_line_summary


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
    
def get_summarized_progress(conn, book_id, chapter_order, last_paragraph):
    """
    DB에서 이벤트를 조회하고, 즉시 OpenAI를 통해 3줄 요약을 생성하여 반환합니다.
    """
    cur = None
    try:
        cur = conn.cursor()
        
        query = """
        SELECT jsonb_agg(chapter_group)
        FROM (
            SELECT 
                c.chapter_order,
                jsonb_agg(
                    jsonb_build_object(
                        'order', e.event_order,
                        'title', e.short_title,
                        'summary', e.summary
                    ) ORDER BY e.event_order ASC
                ) AS events
            FROM readpoint.event e
            INNER JOIN readpoint.chapter c ON e.chapter_id = c.chapter_id
            WHERE e.books_id = %s
              AND c.chapter_order >= 2
              AND (
                  c.chapter_order < %s
                  OR 
                  (c.chapter_order = %s AND e.start_paragraph_id <= %s)
              )
            GROUP BY c.chapter_order
            ORDER BY c.chapter_order ASC
        ) chapter_group;
        """
        
        cur.execute(query, (book_id, chapter_order, chapter_order, last_paragraph))
        result = cur.fetchone()[0]
        
        events_data = result if result is not None else []
        
        # 데이터가 있다면 요약본 생성
        if not events_data:
            return {"status": "no_data", "summary": "아직 읽은 기록이 없습니다."}
            
        # OpenAI 서비스 함수 호출
        three_line_summary = get_three_line_summary(events_data)
        
        # 결과값을 JSON 형태(딕셔너리)로 반환
        return {
            "status": "success",
            "summary": three_line_summary
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
        
    finally:
        if cur: cur.close()
        # conn은 외부에서 관리할 수도 있으므로 상황에 따라 close 여부 결정
        # if conn: conn.close()