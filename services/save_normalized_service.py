import json


def load_alias_map(cur, books_id: int) -> dict:
    cur.execute(
        """
        SELECT alias_name, canonical_name
        FROM character_alias_map
        WHERE books_id = %s;
        """,
        (books_id,)
    )
    return {alias: canonical for alias, canonical in cur.fetchall()}


def normalize_name(name: str, alias_map: dict) -> str:
    if not name:
        return name
    return alias_map.get(name.strip(), name.strip())


def get_or_create_character(cur, books_id, name, role=None, description=None):
    cur.execute(
        """
        SELECT character_id
        FROM character
        WHERE books_id = %s
          AND character_name = %s;
        """,
        (books_id, name)
    )
    row = cur.fetchone()

    if row:
        character_id = row[0]
        cur.execute(
            """
            UPDATE character
            SET role = COALESCE(NULLIF(%s, ''), role),
                description = COALESCE(NULLIF(%s, ''), description)
            WHERE character_id = %s;
            """,
            (role, description, character_id)
        )
        return character_id

    cur.execute(
        """
        INSERT INTO character (
            books_id,
            character_name,
            role,
            description
        )
        VALUES (%s, %s, %s, %s)
        RETURNING character_id;
        """,
        (books_id, name, role, description)
    )
    return cur.fetchone()[0]


def run_save_normalized_analysis(conn, books_id: int):
    with conn.cursor() as cur:

        alias_map = load_alias_map(cur, books_id)

        cur.execute(
            """
            SELECT raw_id, chapter_id, chapter_order, chapter_title, raw_json
            FROM chapter_analysis_raw
            WHERE books_id = %s
            ORDER BY chapter_order;
            """,
            (books_id,)
        )
        rows = cur.fetchall()

        if not rows:
            return {"error": "chapter_analysis_raw not found"}


        character_name_to_id = {}
        saved_event_count = 0
        saved_event_character_count = 0
        saved_relationship_count = 0

        for raw_id, chapter_id, chapter_order, chapter_title, raw_json in rows:
            if isinstance(raw_json, str):
                data = json.loads(raw_json)
            else:
                data = raw_json

            print("=" * 80)
            print(f"SAVE CHAPTER [{chapter_order}] {chapter_title}")
            print("=" * 80)

            # 1. Character 저장
            for ch in data.get("characters", []):
                name = normalize_name(ch.get("name"), alias_map)
                role = ch.get("role")
                description = ch.get("description")

                if not name:
                    continue

                character_id = get_or_create_character(
                    cur,
                    books_id,
                    name,
                    role,
                    description
                )
                character_name_to_id[name] = character_id

            # 2. Event 저장
            event_short_title_to_id = {}

            for idx, ev in enumerate(data.get("events", []), start=1):
                short_title = ev.get("short_title")
                summary = ev.get("summary")
                evidence = ev.get("evidence")
                start_po = ev.get("start_paragraph_order")
                end_po = ev.get("end_paragraph_order")

                cur.execute(
                    """
                    INSERT INTO event (
                        books_id,
                        chapter_id,
                        event_order,
                        short_title,
                        summary,
                        evidence,
                        start_paragraph_id,
                        end_paragraph_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (books_id, chapter_id, event_order)
                    DO UPDATE SET
                        short_title = EXCLUDED.short_title,
                        summary = EXCLUDED.summary,
                        evidence = EXCLUDED.evidence,
                        start_paragraph_id = EXCLUDED.start_paragraph_id,
                        end_paragraph_id = EXCLUDED.end_paragraph_id
                    RETURNING event_id;
                    """,
                    (
                        books_id,
                        chapter_id,
                        idx,
                        short_title,
                        summary,
                        evidence,
                        start_po,
                        end_po
                    )
                )

                event_id = cur.fetchone()[0]
                saved_event_count += 1

                if short_title:
                    event_short_title_to_id[short_title] = event_id

                # 3. Event_Character 저장
                for ev_ch in ev.get("characters", []):
                    ev_ch_name = normalize_name(ev_ch.get("name"), alias_map)
                    role_in_event = ev_ch.get("role_in_event")

                    if not ev_ch_name:
                        continue

                    if ev_ch_name not in character_name_to_id:
                        character_name_to_id[ev_ch_name] = get_or_create_character(
                            cur,
                            books_id,
                            ev_ch_name
                        )

                    cur.execute(
                        """
                        INSERT INTO event_character (
                            event_id,
                            character_id,
                            role_in_event
                        )
                        VALUES (%s, %s, %s)
                        ON CONFLICT (event_id, character_id)
                        DO UPDATE SET
                            role_in_event = EXCLUDED.role_in_event;
                        """,
                        (
                            event_id,
                            character_name_to_id[ev_ch_name],
                            role_in_event
                        )
                    )
                    saved_event_character_count += 1

            # 4. Relationship 저장
            for rel in data.get("relationships", []):
                source_name = normalize_name(rel.get("source"), alias_map)
                target_name = normalize_name(rel.get("target"), alias_map)

                if not source_name or not target_name:
                    continue

                if source_name not in character_name_to_id:
                    character_name_to_id[source_name] = get_or_create_character(
                        cur,
                        books_id,
                        source_name
                    )

                if target_name not in character_name_to_id:
                    character_name_to_id[target_name] = get_or_create_character(
                        cur,
                        books_id,
                        target_name
                    )

                related_event_short_title = rel.get("related_event_short_title")
                related_event_id = event_short_title_to_id.get(
                    related_event_short_title
                )

                cur.execute(
                    """
                    INSERT INTO relationship_change (
                        books_id,
                        chapter_id,
                        related_event_id,
                        source_character_id,
                        target_character_id,
                        relation,
                        change_summary,
                        evidence,
                        start_paragraph_order,
                        end_paragraph_order
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (
                        books_id,
                        chapter_id,
                        source_character_id,
                        target_character_id,
                        relation,
                        start_paragraph_order,
                        end_paragraph_order
                    )
                    DO UPDATE SET
                        related_event_id = EXCLUDED.related_event_id,
                        change_summary = EXCLUDED.change_summary,
                        evidence = EXCLUDED.evidence;
                    """,
                    (
                        books_id,
                        chapter_id,
                        related_event_id,
                        character_name_to_id[source_name],
                        character_name_to_id[target_name],
                        rel.get("relation"),
                        rel.get("change_summary"),
                        rel.get("evidence"),
                        rel.get("start_paragraph_order"),
                        rel.get("end_paragraph_order")
                    )
                )
                saved_relationship_count += 1

        conn.commit()

        return {
            "status": "success",
            "message": "normalized analysis saved",
            "books_id": books_id,
            "raw_count": len(rows),
            "character_count": len(character_name_to_id),
            "event_count": saved_event_count,
            "event_character_count": saved_event_character_count,
            "relationship_count": saved_relationship_count
        }