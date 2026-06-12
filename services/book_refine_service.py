import json
import logging

from services.openai_client import client, DEPLOYMENT


def run_book_graph_refine(conn, books_id: int):
    logging.info(f"book_graph_refine start books_id={books_id}")

    payload = build_refine_input(conn, books_id)

    logging.info(
        f"payload counts: "
        f"characters={len(payload['characters'])}, "
        f"events={len(payload['events'])}, "
        f"relationships={len(payload['relationships'])}"
    )

    if not payload["characters"] and not payload["events"] and not payload["relationships"]:
        logging.warning(f"No normalized data found books_id={books_id}")
        return {
            "status": "error",
            "message": "No normalized data found",
            "books_id": books_id
        }

    result = {
        "characters": [],
        "events": [],
        "relationships": []
    }

    if payload["characters"]:
        logging.info("===== CHARACTER REFINE START =====")
        character_payload = {
            "books_id": books_id,
            "characters": payload["characters"]
        }
        character_result = call_character_refine_llm(character_payload)
        result["characters"] = character_result.get("characters", [])
        logging.info("===== CHARACTER REFINE END =====")

    if payload["events"]:
        logging.info("===== EVENT REFINE START =====")
        event_payload = {
            "books_id": books_id,
            "events": payload["events"]
        }
        event_result = call_event_refine_llm(event_payload)
        result["events"] = event_result.get("events", [])
        logging.info("===== EVENT REFINE END =====")

    if payload["relationships"]:
        logging.info("===== RELATIONSHIP REFINE START =====")
        relationship_payload = {
            "books_id": books_id,
            "relationships": payload["relationships"]
        }
        relationship_result = call_relationship_refine_llm(relationship_payload)
        result["relationships"] = relationship_result.get("relationships", [])
        logging.info("===== RELATIONSHIP REFINE END =====")

    logging.info(
        f"LLM result counts: "
        f"characters={len(result.get('characters', []))}, "
        f"events={len(result.get('events', []))}, "
        f"relationships={len(result.get('relationships', []))}"
    )

    logging.info("===== DB UPDATE START =====")

    update_refine_result(conn, books_id, result)
    conn.commit()

    logging.info("===== DB UPDATE END =====")

    return {
        "status": "success",
        "message": "book_graph_refine completed",
        "books_id": books_id,
        "character_count": len(result.get("characters", [])),
        "event_count": len(result.get("events", [])),
        "relationship_count": len(result.get("relationships", [])),
        "result": result
    }

def build_refine_input(conn, books_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                character_id,
                character_name,
                role,
                description
            FROM character
            WHERE books_id = %s
            ORDER BY character_id;
            """,
            (books_id,)
        )
        characters = [
            {
                "character_id": row[0],
                "name": row[1],
                "role": row[2],
                "description": row[3]
            }
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT
                event_id,
                chapter_id,
                event_order,
                short_title,
                summary
            FROM event
            WHERE books_id = %s
            ORDER BY chapter_id, event_order;
            """,
            (books_id,)
        )
        events = [
            {
                "event_id": row[0],
                "chapter_id": row[1],
                "event_order": row[2],
                "short_title": row[3],
                "summary": row[4]
            }
            for row in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT
                rc.relationship_change_id,
                rc.chapter_id,
                rc.related_event_id,
                sc.character_name AS source_name,
                tc.character_name AS target_name,
                rc.relation,
                rc.change_summary
            FROM relationship_change rc
            JOIN character sc
              ON rc.source_character_id = sc.character_id
            JOIN character tc
              ON rc.target_character_id = tc.character_id
            WHERE rc.books_id = %s
            ORDER BY rc.chapter_id, rc.relationship_change_id;
            """,
            (books_id,)
        )
        relationships = [
            {
                "relationship_change_id": row[0],
                "chapter_id": row[1],
                "related_event_id": row[2],
                "source": row[3],
                "target": row[4],
                "relation": row[5],
                "change_summary": row[6]
            }
            for row in cur.fetchall()
        ]

    return {
        "books_id": books_id,
        "characters": characters,
        "events": events,
        "relationships": relationships
    }



def call_character_refine_llm(payload: dict):
    prompt = f"""
당신은 소설 인물 데이터를 정제하는 분석기이다.

characters 각각에 대해 character_type과 importance_score를 부여하라.

character_type:
- MAIN_CHARACTER: 소설 전체 전개에 핵심적인 주요 인물
- SUPPORT_CHARACTER: 주요 인물을 돕거나 갈등을 만드는 보조 인물
- ROLE_ONLY: 이름이 아니라 직책/호칭 중심 인물
- GROUP: 개인이 아니라 집단

importance_score:
- 0.00 ~ 1.00 사이 숫자
- 소설 전체 이해에 중요할수록 높게 부여
- 단역, 단순 호칭, 일회성 인물은 낮게 부여

중요 규칙:
- 입력에 있는 character_id는 반드시 그대로 반환하라.
- 입력에 없는 인물을 새로 만들지 마라.
- 반드시 JSON만 반환하라.

반환 형식:
{{
  "characters": [
    {{
      "character_id": 0,
      "character_type": "MAIN_CHARACTER",
      "importance_score": 0.95
    }}
  ]
}}

입력 데이터:
{json.dumps(payload, ensure_ascii=False)}
"""

    logging.info(f"character prompt_size={len(prompt):,} chars")
    logging.info("OpenAI character refine START")

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": "당신은 소설 인물 정제기이다. 반드시 JSON만 반환한다."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        timeout=180
    )

    logging.info("OpenAI character refine END")

    return json.loads(response.choices[0].message.content)


def call_event_refine_llm(payload: dict):
    prompt = f"""
당신은 소설 사건 데이터를 정제하는 분석기이다.

events 각각에 대해 event_type, importance_score, is_core_event, is_sensitive를 부여하라.

event_type:
- CORE_EVENT: 전체 줄거리 이해에 반드시 필요한 핵심 사건
- SUPPORT_EVENT: 핵심 사건을 이해하는 데 도움이 되는 보조 사건
- MINOR_EVENT: 일상적 장면, 단순 이동, 단순 식사, 단순 등장 등 중요도가 낮은 사건

importance_score:
- 0.00 ~ 1.00 사이 숫자
- 소설 전체 이해에 중요할수록 높게 부여
- 인물 성장, 좌절, 갈등 시작, 갈등 심화, 관계 변화, 전환점, 결말에 영향을 주는 사건은 높게 부여
- 단순 장면, 단순 이동, 일상 묘사는 낮게 부여

is_core_event:
- CORE_EVENT이면 true
- 아니면 false

is_sensitive:
- 폭력, 살해, 자해, 죽음, 질병 악화, 체포, 감금, 학대, 성적 위협, 차별, 강압 등 사용자가 불편하게 느낄 수 있는 사건이면 true
- 일반 갈등, 단순 말다툼, 일상 사건은 false

중요 규칙:
- 입력에 있는 event_id는 반드시 그대로 반환하라.
- 입력에 없는 사건을 새로 만들지 마라.
- 반드시 JSON만 반환하라.

반환 형식:
{{
  "events": [
    {{
      "event_id": 0,
      "event_type": "CORE_EVENT",
      "importance_score": 0.95,
      "is_core_event": true,
      "is_sensitive": false
    }}
  ]
}}

입력 데이터:
{json.dumps(payload, ensure_ascii=False)}
"""

    logging.info(f"event prompt_size={len(prompt):,} chars")
    logging.info("OpenAI event refine START")

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": "당신은 소설 사건 정제기이다. 반드시 JSON만 반환한다."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        timeout=180
    )

    logging.info("OpenAI event refine END")

    return json.loads(response.choices[0].message.content)


def call_relationship_refine_llm(payload: dict):
    prompt = f"""
당신은 소설 인물 관계 데이터를 정제하는 분석기이다.

relationships 각각에 대해 relation_category, importance_score, is_core_relation을 부여하라.

relation_category:
- RELATIONSHIP:
  두 인물 사이에 일정 기간 이상 유지되는 관계 상태이다.
  감정, 신분, 소속, 혈연, 애정, 대립, 의존, 협력, 지배, 단절처럼 인물 관계를 설명할 수 있으면 RELATIONSHIP으로 분류한다.

- INTERACTION:
  특정 사건 안에서만 발생한 행동, 반응, 도움, 대화, 처치, 신고, 설득, 약속, 제안, 명령, 공격 등이다.
  지속적인 관계 상태가 아니라 사건 속 행동이면 INTERACTION으로 분류한다.

주의:
- 입력된 relation 값은 절대 수정하지 마라.
- relation을 표준 관계명으로 바꾸지 마라.
- relation_category만 RELATIONSHIP 또는 INTERACTION 중 하나로 분류하라.
- “약속”은 보통 INTERACTION이지만, 약혼/혼인처럼 지속 관계 상태면 RELATIONSHIP으로 볼 수 있다.
- “보호”, “의존”, “지지”는 일회성 행동이면 INTERACTION, 지속적 관계 상태이면 RELATIONSHIP으로 판단하라.

importance_score:
- 0.00 ~ 1.00 사이 숫자
- 주요 인물 간 핵심 관계일수록 높게 부여
- 단순 대화, 일회성 도움, 단순 만남은 낮게 부여

is_core_relation:
- 소설 전체 인물 관계 이해에 중요하면 true
- 단순 상호작용이면 false

중요 규칙:
- 입력에 있는 relationship_change_id는 반드시 그대로 반환하라.
- 입력에 없는 관계를 새로 만들지 마라.
- 반드시 JSON만 반환하라.

반환 형식:
{{
  "relationships": [
    {{
      "relationship_change_id": 0,
      "relation_category": "RELATIONSHIP",
      "importance_score": 0.95,
      "is_core_relation": true
    }}
  ]
}}

입력 데이터:
{json.dumps(payload, ensure_ascii=False)}
"""

    logging.info(f"relationship prompt_size={len(prompt):,} chars")
    logging.info("OpenAI relationship refine START")

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {"role": "system", "content": "당신은 소설 관계 정제기이다. 반드시 JSON만 반환한다."},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        timeout=180
    )

    logging.info("OpenAI relationship refine END")

    return json.loads(response.choices[0].message.content)


def update_refine_result(conn, books_id: int, result: dict):
    with conn.cursor() as cur:
        for item in result.get("characters", []):
            cur.execute(
                """
                UPDATE character
                SET
                    character_type = %s,
                    importance_score = %s
                WHERE books_id = %s
                  AND character_id = %s;
                """,
                (
                    item.get("character_type"),
                    item.get("importance_score"),
                    books_id,
                    item.get("character_id")
                )
            )

        for item in result.get("events", []):
            cur.execute(
                """
                UPDATE event
                SET
                    event_type = %s,
                    importance_score = %s,
                    is_core_event = %s,
                    is_sensitive = %s
                WHERE books_id = %s
                  AND event_id = %s;
                """,
                (
                    item.get("event_type"),
                    item.get("importance_score"),
                    item.get("is_core_event"),
                    item.get("is_sensitive"),
                    books_id,
                    item.get("event_id")
                )
            )

        for item in result.get("relationships", []):
            cur.execute(
                """
                UPDATE relationship_change
                SET
                    relation_category = %s,
                    importance_score = %s,
                    is_core_relation = %s
                WHERE books_id = %s
                  AND relationship_change_id = %s;
                """,
                (
                    item.get("relation_category"),
                    item.get("importance_score"),
                    item.get("is_core_relation"),
                    books_id,
                    item.get("relationship_change_id")
                )
            )