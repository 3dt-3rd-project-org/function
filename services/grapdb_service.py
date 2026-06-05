import logging
import os
from neo4j import GraphDatabase

# Neo4j 환경 변수
NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")

# [수정] 드라이버 객체를 전역 공간에 딱 1번만 빌드하여 싱글톤 커넥션 풀로 재사용합니다.
if NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
else:
    driver = None
    logging.error("❌ Neo4j 환경 변수 로드 실패. 시스템 환경 변수나 local.settings.json을 확인하세요.")

def _migrate_transaction_logic(tx, data):
    book_id = str(data["books_id"])

    for row in data["results"]:
        chapter_id = str(row["chapter_id"])
        chapter_order = row["chapter_order"]
        chapter_title = row["chapter_title"]

        # 1. 도서 - 챕터 관계 연결
        tx.run(
            """
            MERGE (b:Book {books_id: $book_id})
            MERGE (ch:Chapter {chapter_id: $chapter_id})
            SET ch.title = $chapter_title, ch.chapter_order = $chapter_order
            MERGE (b)-[:HAS_CHAPTER]->(ch)
            """,
            book_id=book_id,
            chapter_id=chapter_id,
            chapter_order=chapter_order,
            chapter_title=chapter_title,
        )

        contents = row["result"]

        # 2. 인물(Character) 노드 생성
        for char in contents.get("characters", []):
            char_id = f"{char['name']}_{book_id}"
            tx.run(
                """
                MERGE (c:Character {character_id: $char_id})
                SET c.character_name = $name, c.role = $role, c.description = $description
                """,
                char_id=char_id,
                name=char["name"],
                role=char.get("role"),
                description=char.get("description"),
            )

        # 3. 사건(Event) 노드 생성 및 관계 연결
        for idx, ev in enumerate(contents.get("events", [])):
            event_id = f"ev_{chapter_id}_{idx}"

            # 3-1. 챕터 -> 사건 연결
            tx.run(
                """
                MATCH (ch:Chapter {chapter_id: $chapter_id})
                MERGE (e:Event {event_id: $event_id})
                SET e.summary = $summary, e.start_paragraph_order = $start_para, e.end_paragraph_order = $end_para
                MERGE (ch)-[:HAS_EVENT]->(e)
                """,
                chapter_id=chapter_id,
                event_id=event_id,
                summary=ev.get("summary"),
                start_para=ev.get("start_paragraph_order"),
                end_para=ev.get("end_paragraph_order"),
            )

            # 3-2. 사건 -> 참여 인물(INVOLVES) 연결
            for ev_char in ev.get("characters", []):
                target_char_id = f"{ev_char['name']}_{book_id}"
                tx.run(
                    """
                    MATCH (e:Event {event_id: $event_id})
                    MATCH (c:Character {character_id: $char_id})
                    MERGE (e)-[r:INVOLVES]->(c)
                    SET r.role_in_event = $role_in_event
                    """,
                    event_id=event_id,
                    char_id=target_char_id,
                    role_in_event=ev_char.get("role_in_event"),
                )

        # 4. 인물 간 관계 변동 이력 (RELATES_TO) 연결
        for r_idx, rel in enumerate(contents.get("relationships", [])):
            src_id = f"{rel['source']}_{book_id}"
            tgt_id = f"{rel['target']}_{book_id}"
            rel_change_id = f"rc_{chapter_id}_{r_idx}"

            tx.run(
                """
                MATCH (c1:Character {character_id: $src_id})
                MATCH (c2:Character {character_id: $tgt_id})
                
                MERGE (c1)-[r:RELATES_TO {chapter_id: $chapter_id}]->(c2)
                SET r.relationship_change_id = $rel_change_id,
                    r.chapter_order = $chapter_order,
                    r.new_relation = $relation,
                    r.change_reason = $change_summary,
                    r.evidence = $evidence,
                    r.start_paragraph_order = $start_para,
                    r.end_paragraph_order = $end_para
                """,
                src_id=src_id,
                tgt_id=tgt_id,
                chapter_id=chapter_id,
                chapter_order=chapter_order,
                rel_change_id=rel_change_id,
                relation=rel.get("relation"),
                change_summary=rel.get("change_summary"),
                evidence=rel.get("evidence"),
                start_para=rel.get("start_paragraph_order"),
                end_para=rel.get("end_paragraph_order"),
            )


def insert_graph_data(json_data):
    if not json_data or "books_id" not in json_data:
        logging.error("❌ 실패: Neo4j에 주입할 데이터 형식이 올바르지 않습니다.")
        return False

    if not driver:
        logging.error("❌ 실패: Neo4j 드라이버가 빌드되지 않아 적재가 불가능합니다.")
        return False

    target_books_id = json_data["books_id"]
    logging.info(f"🔗 [Neo4j] ID 기반 적재 시작 (Target Book ID: {target_books_id})")

    try:
        # 💡 [수정] 매번 함수 안에서 새 드라이버 인스턴스를 열고 닫지 않고, 전역 드라이버의 세션만 빌려 실행합니다.
        with driver.session() as session:
            session.execute_write(_migrate_transaction_logic, json_data)
            
        logging.info(f"[Neo4j] 도서 ID '{target_books_id}' 적재 정상 성공!")
        return True
    except Exception as e:
        logging.error(f"[Neo4j] 마이그레이션 적재 트랜잭션 에러: {str(e)}")
        raise e