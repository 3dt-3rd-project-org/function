# services/progress_summary_service.py

import json
import logging
from psycopg2.extras import RealDictCursor

from services.openai_client import client, DEPLOYMENT


IMPORTANCE_THRESHOLD = 0.6


def fetch_target_events(conn, books_id: int):
    """
    progress_summary를 생성할 대상 사건 목록 조회
    - 중요도 0.6 이상만 사용
    - 책 전체 흐름 순서대로 정렬
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                event_id,
                books_id,
                chapter_id,
                event_order,
                short_title,
                summary,
                start_paragraph_id,
                end_paragraph_id,
                importance_score,
                is_core_event
            FROM event
            WHERE books_id = %s
              AND importance_score >= %s
            ORDER BY start_paragraph_id, end_paragraph_id, event_id;
            """,
            (books_id, IMPORTANCE_THRESHOLD),
        )
        return cur.fetchall()


def build_prompt(previous_cumulative_summary: str, event_row: dict) -> str:
    """
    이전 누적 요약 + 현재 사건 요약을 기반으로
    이어읽기용 리캡 생성
    """

    previous_text = previous_cumulative_summary if previous_cumulative_summary else "없음"

    return f"""
너는 소설 독서 보조 서비스 ReadPoint의 '이어읽기 리캡 생성기'다.

목표:

사용자가 몇 주 또는 몇 달 동안 책을 읽지 않다가
현재 위치에서 다시 읽기 시작한다고 가정하라.

사용자는 현재 사건까지 읽었지만
세부 내용은 대부분 잊어버린 상태다.

사용자가 스토리의 흐름을 빠르게 떠올릴 수 있도록
'기억 복원용 리캡'을 작성하라.

중요:

- 아직 읽지 않은 미래 사건은 절대 포함하지 않는다.
- 현재 사건까지의 내용만 사용한다.
- 미래 내용을 추측하거나 암시하지 않는다.
- 사건을 나열하지 말고 이야기의 흐름을 설명한다.
- 사용자가 "아 맞다!" 하고 기억을 되살릴 수 있게 작성한다.
- 반드시 JSON만 출력한다.

리캡 작성 규칙:

1. 첫 번째 줄
   - 주인공이 현재 어떤 상황에 있는지 설명

2. 두 번째 줄
   - 현재까지 형성된 핵심 인물 관계 또는 갈등 설명

3. 세 번째 줄
   - 현재 이야기의 진행 위치와 중요한 주제 설명
   - 미래 사건 스포일러 금지

summary_3line 규칙:

- 반드시 문자열 3개를 반환
- 각 줄은 1~2문장
- 소설을 읽지 않은 사람도 이해할 수 있게 작성

cumulative_summary_text 규칙:

- 다음 사건 리캡 생성을 위한 내부 누적 요약
- 현재 사건까지의 핵심 흐름 유지
- 1000자 이내

[이전까지의 누적 요약]
{previous_text}

[이번에 새로 도달한 사건]

사건 ID: {event_row["event_id"]}
챕터 ID: {event_row["chapter_id"]}
제목: {event_row["short_title"]}

사건 요약:
{event_row["summary"]}

출력 형식:

{{
  "summary_3line": [
    "첫 번째 줄",
    "두 번째 줄",
    "세 번째 줄"
  ],
  "cumulative_summary_text": "현재 사건까지의 누적 요약"
}}
""".strip()


def call_llm_for_progress_summary(previous_cumulative_summary: str, event_row: dict):
    """
    Azure OpenAI 호출
    """
    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": "너는 소설 내용을 현재 읽은 지점까지만 요약하는 독서 보조 AI다.",
            },
            {
                "role": "user",
                "content": build_prompt(previous_cumulative_summary, event_row),
            },
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    return json.loads(content)


def normalize_summary_3line(summary_3line):
    """
    LLM 결과의 summary_3line을 DB 저장용 TEXT로 변환
    """
    if isinstance(summary_3line, list):
        return "\n".join(summary_3line)

    return str(summary_3line)


def upsert_progress_summary(conn, event_row: dict, llm_result: dict):
    """
    progress_summary 테이블 저장
    """
    summary_3line_text = normalize_summary_3line(llm_result.get("summary_3line", []))
    cumulative_summary_text = llm_result.get("cumulative_summary_text", "")

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO progress_summary (
                books_id,
                event_id,
                chapter_id,
                start_paragraph_id,
                end_paragraph_id,
                summary_3line,
                cumulative_summary_text,
                importance_score,
                is_core_event,
                llm_model,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                NOW()
            )
            ON CONFLICT (books_id, event_id)
            DO UPDATE SET
                chapter_id = EXCLUDED.chapter_id,
                start_paragraph_id = EXCLUDED.start_paragraph_id,
                end_paragraph_id = EXCLUDED.end_paragraph_id,
                summary_3line = EXCLUDED.summary_3line,
                cumulative_summary_text = EXCLUDED.cumulative_summary_text,
                importance_score = EXCLUDED.importance_score,
                is_core_event = EXCLUDED.is_core_event,
                llm_model = EXCLUDED.llm_model,
                updated_at = NOW();
            """,
            (
                event_row["books_id"],
                event_row["event_id"],
                event_row["chapter_id"],
                event_row["start_paragraph_id"],
                event_row["end_paragraph_id"],
                summary_3line_text,
                cumulative_summary_text,
                event_row["importance_score"],
                event_row["is_core_event"],
                DEPLOYMENT,
            ),
        )


def generate_progress_summaries(conn, books_id: int):
    """
    books_id 기준으로 중요 사건마다 이어읽기 요약 생성
    """
    events = fetch_target_events(conn, books_id)
    events = events[:5]

    previous_cumulative_summary = ""
    saved_count = 0

    logging.info(
        "progress_summary generation started. books_id=%s, target_event_count=%s",
        books_id,
        len(events),
    )

    for event_row in events:
        logging.info(
            "generating progress_summary. books_id=%s, event_id=%s, title=%s",
            books_id,
            event_row["event_id"],
            event_row["short_title"],
        )

        llm_result = call_llm_for_progress_summary(
            previous_cumulative_summary,
            event_row,
        )

        upsert_progress_summary(conn, event_row, llm_result)

        previous_cumulative_summary = llm_result.get("cumulative_summary_text", "")
        saved_count += 1

    conn.commit()

    return {
        "status": "success",
        "books_id": books_id,
        "target_event_count": len(events),
        "saved_count": saved_count,
    }