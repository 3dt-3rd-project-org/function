import json
import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor

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


# 26.6.4 -- 미연
def fetch_and_transform_chapter_raw(conn, target_books_id: int):
    cursor = None
    try:
        # dict 형태로 데이터를 편하게 핸들링하기 위해 RealDictCursor 사용
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # -------------------------------------------------------------
        # 1. 인물(character) 테이블 조회
        # -------------------------------------------------------------
        char_query = """
            SELECT character_id, character_name, role, description 
            FROM readpoint.character 
            WHERE books_id = %s;
        """
        cursor.execute(char_query, (target_books_id,))
        characters_rows = cursor.fetchall()

        if not characters_rows:
            return None

        # ID 기반 데이터를 이름 매핑 문자열로 번역하기 위한 변환 매핑 사전 구축
        char_name_map = {c["character_id"]: c["character_name"] for c in characters_rows}

        # -------------------------------------------------------------
        # 2. 사건(event) 테이블 조회
        # -------------------------------------------------------------
        event_query = """
            SELECT event_id, chapter_id, event_order, summary, evidence, 
                   start_paragraph_id, end_paragraph_id, short_title
            FROM readpoint.event
            WHERE books_id = %s
            ORDER BY chapter_id ASC, event_order ASC;
        """
        cursor.execute(event_query, (target_books_id,))
        event_rows = cursor.fetchall()

        # -------------------------------------------------------------
        # 3. 사건별 인물 매핑(event_character) 테이블 조회 (INNER JOIN 필수)
        # -------------------------------------------------------------
        ev_char_query = """
            SELECT ec.event_id, ec.character_id, ec.role_in_event
            FROM readpoint.event_character ec
            INNER JOIN readpoint.event e ON ec.event_id = e.event_id
            WHERE e.books_id = %s;
        """
        cursor.execute(ev_char_query, (target_books_id,))
        ev_char_rows = cursor.fetchall()

        # event_id 별로 참여 인물들을 묶어줄 매핑 딕셔너리 생성
        ev_char_map = {}
        for ec in ev_char_rows:
            ev_id = ec["event_id"]
            if ev_id not in ev_char_map:
                ev_char_map[ev_id] = []
            
            c_id = ec["character_id"]
            c_name = char_name_map.get(c_id, f"Unknown_{c_id}")
            ev_char_map[ev_id].append({
                "name": c_name,
                "role_in_event": ec["role_in_event"]
            })

        # -------------------------------------------------------------
        # 4. 관계 변동 이력(relationship_change) 테이블 조회
        # -------------------------------------------------------------
        rel_query = """
            SELECT chapter_id, source_character_id, target_character_id, 
                   relation, change_summary, evidence, start_paragraph_order, end_paragraph_order
            FROM readpoint.relationship_change
            WHERE books_id = %s;
        """
        cursor.execute(rel_query, (target_books_id,))
        rel_rows = cursor.fetchall()

        # -------------------------------------------------------------
        # ⚙️ [트리 구조 데이터 조립]
        # -------------------------------------------------------------
        combined_data = {"books_id": str(target_books_id), "results": []}
        chapters_map = {}

        # 챕터별로 사건 및 공통 캐릭터 데이터 기본 뼈대 안착
        for idx, ev in enumerate(event_rows):
            ch_id = str(ev["chapter_id"])

            if ch_id not in chapters_map:
                chapters_map[ch_id] = {
                    "chapter_id": ch_id,
                    "chapter_order": idx + 1,        # 순서 및 타이틀은 정규화 테이블에 없으므로 임시 대체
                    "chapter_title": f"{ch_id} 챕터",
                    "result": {
                        "characters": [
                            {
                                "name": c["character_name"],
                                "role": c["role"],
                                "description": c["description"],
                            }
                            for c in characters_rows
                        ]
                    },
                    "events_list": [],
                    "relationships_list": [],
                }

            # 이 사건에 속한 인물 목록 조회 및 주입
            linked_characters = ev_char_map.get(ev["event_id"], [])

            event_item = {
                "summary": ev["summary"],
                "start_paragraph_order": ev["start_paragraph_id"],
                "end_paragraph_order": ev["end_paragraph_id"],
                "characters": linked_characters,
            }
            chapters_map[ch_id]["events_list"].append(event_item)

        # 관계 변동 데이터를 각 챕터별 맵에 매핑
        for rel in rel_rows:
            ch_id = str(rel["chapter_id"])
            if ch_id in chapters_map:
                src_name = char_name_map.get(rel["source_character_id"], "Unknown")
                tgt_name = char_name_map.get(rel["target_character_id"], "Unknown")

                rel_item = {
                    "source": src_name,
                    "target": tgt_name,
                    "relation": rel["relation"],
                    "change_summary": rel["change_summary"],
                    "evidence": rel["evidence"],
                    "start_paragraph_order": rel["start_paragraph_order"],
                    "end_paragraph_order": rel["end_paragraph_order"],
                }
                chapters_map[ch_id]["relationships_list"].append(rel_item)

        # 딕셔너리 구조를 최종 반환 규격 리스트로 재변환
        for ch_data in chapters_map.values():
            chapter_final = {
                "chapter_id": ch_data["chapter_id"],
                "chapter_order": ch_data["chapter_order"],
                "chapter_title": ch_data["chapter_title"],
                "result": {
                    "characters": ch_data["result"]["characters"],
                    "events": ch_data["events_list"],
                    "relationships": ch_data["relationships_list"],
                },
            }
            combined_data["results"].append(chapter_final)

        return combined_data

    except Exception as e:
        raise e
    finally:
        if cursor:
            cursor.close()

# 3줄 요약 저장
def save_three_line_summary(user_id, book_id, chapter_id, summary):
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        query = """
        UPDATE readpoint.reading_logs
        SET three_line_summary = %s
        WHERE user_id = %s AND book_id = %s AND chapter_id = %s;
        """
        cur.execute(query, (summary, user_id, book_id, chapter_id))
        conn.commit()
        
    except Exception as e:
        if conn:
            conn.rollback() # 에러 발생 시 트랜잭션 롤백
        logging.error(f"DB 업데이트 중 오류 발생: {e}")
        raise e
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()