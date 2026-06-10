# services/progress_summary_service.py

import json
import logging
from psycopg2.extras import RealDictCursor

from services.openai_client import client, DEPLOYMENT


def fetch_event_characters(conn, event_id: int):
    """
    사건에 연결된 등장인물 목록 조회
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT
                c.character_name,
                ec.role_in_event
            FROM event_character ec
            JOIN character c
              ON ec.character_id = c.character_id
            WHERE ec.event_id = %s
            ORDER BY
                CASE
                    WHEN ec.role_in_event = '주인공' THEN 1
                    WHEN ec.role_in_event = '피해자' THEN 2
                    WHEN ec.role_in_event = '협박자' THEN 3
                    ELSE 9
                END,
                c.importance_score DESC;
            """,
            (event_id,)
        )
        return cur.fetchall()



def build_prompt(previous_cumulative_summary: str, event_row: dict, event_characters: list | None = None) -> str:
    """
    이전 누적 요약 + 현재 사건 요약을 기반으로
    이어읽기용 리캡 생성
    """

    previous_text = previous_cumulative_summary if previous_cumulative_summary else "없음"
    if event_characters:
        character_text = "\n".join(
        [f"- {row['character_name']} ({row['role_in_event']})" for row in event_characters])
    else:
        character_text = "없음"

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

[이번 사건 주요 등장인물]
{character_text}

인물명 규칙:
- 등장인물 이름은 사건 요약에 나온 표현을 최대한 유지한다.
- '주인공', '소년', '그', '그녀' 같은 일반 표현으로 치환하지 않는다.
- 인물 이름이 명확하면 반드시 이름으로 작성한다.
- 이름이 불명확할 때만 '화자' 또는 '인물'이라는 표현을 사용한다.
[이번 사건 주요 등장인물]에 있는 이름을 우선 사용한다.

리캡 작성 규칙:

summary_3line은 현재 사건 하나만 설명하는 요약이 아니다.
사용자가 현재 사건까지 읽은 상태에서 전체 흐름을 기억하도록 작성한다.
- 직전 사건만 설명하지 않는다.
- 현재 사건까지 이어져 온 주요 흐름을 포함한다.
- 최근 3~5개의 핵심 사건이 자연스럽게 녹아들어야 한다.

1. 첫 번째 줄
   - 지금까지 중심 인물이 어떤 과정을 거쳐 현재 상태에 왔는지 설명
   - 현재 사건만 단독으로 설명하지 않는다

2. 두 번째 줄
   - 현재까지 형성된 핵심 인물 관계나 갈등을 설명
   - 이번 사건으로 그 관계나 갈등이 어떻게 달라졌는지 포함

3. 세 번째 줄
   - 현재 이야기의 흐름이 어디까지 왔는지 설명
   - 앞으로 읽기 위해 필요한 맥락을 자연스럽게 정리
   - "기억하라", "기억하면 된다" 같은 표현 금지

summary_3line 규칙:

- 반드시 문자열 3개를 반환
- 각 줄은 1~2문장
- 소설을 읽지 않은 사람도 이해할 수 있게 작성

문체 규칙:

- 독자에게 설명하는 해설자 말투를 사용하지 않는다.
- "기억하라", "기억하면 된다", "독자는", "현재 위치는", "현재 상태는" 같은 표현을 사용하지 않는다.
- 분석 보고서처럼 쓰지 않는다.
- 소설 줄거리를 자연스럽게 되짚어 주는 말투를 사용한다.
- 이어읽기 직전에 보는 리캡처럼 작성한다.
- "이야기는 ~ 지점에 와 있다" 표현 금지
- "현재 ~ 상태다" 표현 금지
- "국면", "단계", "위치", "흐름" 같은 분석 용어 사용 금지
- 사건을 설명하는 대신 인물의 경험을 따라가듯 작성한다.

cumulative_summary_text 규칙:

- 다음 사건 리캡 생성을 위한 내부 상태 요약이다.
- 사건을 처음부터 끝까지 나열하지 않는다.
- 현재 시점에서 중요한 상태만 남긴다.
- 오래된 사건은 결과만 남기고 세부 과정은 줄인다.
- 인물 관계, 현재 갈등, 중심 인물의 내면 상태를 우선 유지한다.
- 다음 사건과 연결될 수 있는 맥락만 남긴다.
- 600자 이내로 작성한다.
- 이미 해결된 갈등은 결과만 남긴다.
- 중요도가 낮은 사건은 누적 요약에서 제거할 수 있다.
- 현재 줄거리에 영향을 주는 요소만 유지한다.

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


def call_llm_for_progress_summary(
    previous_cumulative_summary: str,
    event_row: dict,
    event_characters: list | None = None
):
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
                "content": build_prompt(
                    previous_cumulative_summary,
                    event_row,
                    event_characters,
                ),
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





def fetch_event_by_id(conn, books_id: int, event_id: int):
    """
    특정 사건 1개 조회
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
              AND event_id = %s;
            """,
            (books_id, event_id),
        )
        return cur.fetchone()
    


def fetch_previous_cumulative_summary(conn, books_id: int, event_row: dict):
    """
    현재 사건 이전의 가장 가까운 progress_summary에서 cumulative_summary_text 조회
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cumulative_summary_text
            FROM progress_summary
            WHERE books_id = %s
              AND (
                    chapter_id < %s
                    OR (
                        chapter_id = %s
                        AND end_paragraph_id < %s
                    )
              )
            ORDER BY chapter_id DESC, end_paragraph_id DESC, event_id DESC
            LIMIT 1;
            """,
            (
                books_id,
                event_row["chapter_id"],
                event_row["chapter_id"],
                event_row["end_paragraph_id"],
            ),
        )

        row = cur.fetchone()
        return row[0] if row else ""
    
def generate_progress_summary_for_event(conn, books_id: int, event_id: int):
    """
    ADF ForEach용: 특정 사건 1개에 대한 이어읽기 요약 생성
    - 이전 누적 요약은 DB에서 조회
    """
    event_row = fetch_event_by_id(conn, books_id, event_id)

    if not event_row:
        return {
            "status": "error",
            "message": "event not found",
            "books_id": books_id,
            "event_id": event_id,
        }

    previous_cumulative_summary = fetch_previous_cumulative_summary(
        conn,
        books_id,
        event_row,
    )

    event_characters = fetch_event_characters(conn, event_id)

    llm_result = call_llm_for_progress_summary(
        previous_cumulative_summary,
        event_row,
        event_characters,
    )

    upsert_progress_summary(conn, event_row, llm_result)
    conn.commit()

    return {
        "status": "success",
        "message": "progress summary saved",
        "books_id": books_id,
        "event_id": event_id,
        "chapter_id": event_row["chapter_id"],
        "start_paragraph_id": event_row["start_paragraph_id"],
        "end_paragraph_id": event_row["end_paragraph_id"],
    }