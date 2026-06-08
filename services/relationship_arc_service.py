import json
from collections import defaultdict

from services.openai_client import client, DEPLOYMENT


def run_relationship_arc_test(conn, books_id: int, min_event_importance: float = 0.5):
    rows = fetch_relationship_changes(conn, books_id, min_event_importance)
    chapters = group_by_chapter(rows)

    result = call_relationship_turning_point_llm({
        "books_id": books_id,
        "chapters": chapters
    })

    return {
        "status": "success",
        "message": "relationship_turning_point_test completed",
        "books_id": books_id,
        "chapter_count": len(chapters),
        "result": result
    }


def fetch_relationship_changes(conn, books_id: int, min_event_importance: float):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                rc.books_id,
                rc.chapter_id,
                rc.related_event_id AS event_id,
                rc.relationship_change_id,
                rc.start_paragraph_order,
                rc.end_paragraph_order,
                sc.character_name AS source,
                tc.character_name AS target,
                rc.relation,
                rc.relation_category,
                e.short_title,
                e.summary AS event_summary,
                e.importance_score AS event_importance_score,
                rc.importance_score AS relationship_importance_score,
                rc.is_core_relation,
                rc.change_summary
            FROM relationship_change rc
            JOIN event e
                ON rc.related_event_id = e.event_id
            JOIN character sc
                ON rc.source_character_id = sc.character_id
            JOIN character tc
                ON rc.target_character_id = tc.character_id
            WHERE e.books_id = %s
              AND e.importance_score >= %s
            ORDER BY
                rc.chapter_id ASC,
                rc.related_event_id ASC,
                rc.start_paragraph_order ASC;
            """,
            (books_id, min_event_importance)
        )

        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def group_by_chapter(rows):
    grouped = defaultdict(list)

    for row in rows:
        grouped[row["chapter_id"]].append({
            "relationship_change_id": row["relationship_change_id"],
            "chapter_id": row["chapter_id"],
            "event_id": row["event_id"],
            "start_paragraph_order": row["start_paragraph_order"],
            "end_paragraph_order": row["end_paragraph_order"],
            "source": row["source"],
            "target": row["target"],
            "relation": row["relation"],
            "relation_category": row["relation_category"],
            "short_title": row["short_title"],
            "event_importance_score": float(row["event_importance_score"] or 0),
            "relationship_importance_score": float(row["relationship_importance_score"] or 0),
            "is_core_relation": row["is_core_relation"],
            "change_summary": row["change_summary"],
            "event_summary": row["event_summary"]
        })

    chapters = []

    for chapter_id, changes in grouped.items():
        chapters.append({
            "chapter_id": chapter_id,
            "changes": changes
        })

    return chapters


def call_relationship_turning_point_llm(payload: dict):
    prompt_body = """
당신은 소설의 챕터별 인물 관계 변화를 정리하는 분석기이다.

입력 데이터는 챕터별 relationship_change 목록이다.

중요:

story는 소설의 중심 인물 관점으로 작성한다.

중심 인물은 입력 데이터에서
importance_score가 가장 높은 MAIN_CHARACTER이다.

display_title은 중심 인물이 상대를 어떻게 느꼈는지 표현한다.
상대방 관점으로 작성하지 마라.

목표:
관계 단어를 요약하는 것이 목적이 아니다.
두 인물이 서로에게 어떤 의미를 가지게 되었는지 설명하는 것이 목적이다.
사건 자체보다 "상대가 어떤 존재였는가"를 중심으로 정리한다.
독자가 소설을 읽지 않았어도 두 사람의 관계를 이해할 수 있어야 한다.
관계 변화의 결과보다 관계가 만들어진 이유와 의미를 우선 설명한다.
모든 표현은 입력 데이터만 근거로 작성한다.
- 각 챕터 안에서 인물쌍별로 중요한 관계 변화를 고른다.
- 한 챕터에서 같은 인물쌍은 최대 1개만 선택한다.
- 한 챕터 전체에서는 최대 1~3개만 선택한다.
- 책 전체 요약을 하지 마라.
- 챕터 전체 줄거리 요약을 하지 마라.
- 반드시 source와 target 사이의 관계 변화만 설명하라.
- event_summary, short_title, change_summary를 함께 참고해서 판단하라.
- 관계가 여러 번 바뀌어도 같은 챕터 안에서는 가장 중요한 변화 하나로 합쳐라.

display_title 작성 규칙:

* display_title은 사건 제목이 아니다.
* display_title은 상대가 어떤 존재였는지를 표현한다.
* 사용자는 이 제목만 보고도 관계를 이해할 수 있어야 한다.
* "~한 사람", "~한 친구", "~한 존재", "~한 상대" 형태를 우선 사용한다.
* 5~15자 정도로 작성한다.
* 추상적인 단어(신뢰, 의존, 연대, 갈등 등)만 단독으로 사용하지 않는다.

좋지 않은 예:

* 신뢰
* 갈등
* 협박
* 조력
* 전쟁 소식과 작별
* 집 앞에서 돈 내라며 겁줌

좋은 방향:

* 나를 괴롭히던 사람
* 나를 구해준 친구
* 마음을 이해해준 사람
* 멀어졌지만 잊히지 않은 친구
* 나를 성장시킨 스승
* 사랑하게 된 사람
* 떠나보내야 했던 사람


반환 형식:
{
  "chapter_relationship_points": [
    {
      "chapter_id": 0,
      "points": [
        {
          "order_in_chapter": 1,
          "source": "인물A",
          "target": "인물B",
          "display_title": "사용자에게 보여줄 관계 제목",
          "display_summary": "두 인물 관계가 어떻게 바뀌었는지 1문장으로 설명한다.",
          "relation_label": "짧은 관계명",
          "event_id": 0,
          "start_paragraph_order": 0,
          "end_paragraph_order": 0,
          "evidence_relationship_change_ids": [0]
        }
      ]
    }
  ]
}

반드시 JSON만 반환하라.
마크다운, 설명문, 코드블록은 쓰지 마라.
"""

    prompt = (
        prompt_body
        + "\n\n입력 데이터:\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": "당신은 소설의 챕터별 인물 관계 변화를 정리하는 분석기이다. 반드시 JSON만 반환한다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        response_format={"type": "json_object"}
    )

    return json.loads(response.choices[0].message.content)