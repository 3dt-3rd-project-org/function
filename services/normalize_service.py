import json
from services.db_service import add_llm_usage
from services.character_normalize_service import normalize_character_aliases


def run_normalize_characters(conn, books_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT chapter_id,
                   chapter_order,
                   chapter_title,
                   raw_json
            FROM chapter_analysis_raw
            WHERE books_id = %s
            ORDER BY chapter_order;
            """,
            (books_id,)
        )

        rows = cur.fetchall()

        if not rows:
            return {
                "error": "chapter_analysis_raw not found"
            }

        character_candidates = []

        for chapter_id, chapter_order, chapter_title, raw_json in rows:
            if isinstance(raw_json, str):
                data = json.loads(raw_json)
            else:
                data = raw_json

            for ch in data.get("characters", []):
                character_candidates.append(
                    {
                        "chapter_id": chapter_id,
                        "chapter_order": chapter_order,
                        "chapter_title": chapter_title,
                        "name": ch.get("name"),
                        "role": ch.get("role"),
                        "description": ch.get("description")
                    }
                )

        print("=" * 80)
        print("CHARACTER CANDIDATES")
        print("=" * 80)
        print(json.dumps(character_candidates, ensure_ascii=False, indent=2))

        openai_result = normalize_character_aliases(character_candidates)

        result = openai_result["data"]
        usage = openai_result["usage"]

        add_llm_usage(
            conn=conn,
            books_id=books_id,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"]
        )

        print("=" * 80)
        print("CHARACTER NORMALIZE RESULT")
        print("=" * 80)
        print(json.dumps(result, ensure_ascii=False, indent=2))

        # 기존 alias map 삭제 후 재생성
        cur.execute(
            """
            DELETE FROM character_alias_map
            WHERE books_id = %s;
            """,
            (books_id,)
        )

        inserted_count = 0

        for ch in result.get("characters", []):
            canonical_name = ch.get("canonical_name")
            aliases = ch.get("aliases", [])
            role = ch.get("role")
            description = ch.get("description")
            confidence = ch.get("confidence")

            if not canonical_name:
                continue

            if canonical_name not in aliases:
                aliases.append(canonical_name)

            for alias_name in aliases:
                if not alias_name:
                    continue

                cur.execute(
                    """
                    INSERT INTO character_alias_map (
                        books_id,
                        canonical_name,
                        alias_name,
                        role,
                        description,
                        confidence,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (books_id, alias_name)
                    DO UPDATE SET
                        canonical_name = EXCLUDED.canonical_name,
                        role = EXCLUDED.role,
                        description = EXCLUDED.description,
                        confidence = EXCLUDED.confidence,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        books_id,
                        canonical_name,
                        alias_name,
                        role,
                        description,
                        confidence
                    )
                )

                inserted_count += 1

        conn.commit()

        return {
            "status": "success",
            "message": "character aliases normalized",
            "books_id": books_id,
            "raw_chapter_count": len(rows),
            "candidate_count": len(character_candidates),
            "canonical_character_count": len(result.get("characters", [])),
            "alias_count": inserted_count,
            "result": result
        }