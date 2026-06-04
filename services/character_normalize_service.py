import json

from services.openai_client import client, DEPLOYMENT


def normalize_character_aliases(character_candidates: list[dict]) -> dict:
    prompt = f"""
당신은 소설 인물명 정규화 전문가이다.

아래는 한 권의 소설에서 챕터별로 추출된 인물 목록이다.

목표:
같은 인물을 하나의 대표 이름(canonical_name)으로 통합하라.

규칙:
- 반드시 JSON만 반환하라.
- 모든 값은 한국어로 작성하라.
- 같은 인물로 판단되는 이름은 aliases에 함께 넣어라.
- "나", "화자", "주인공", "소년"처럼 같은 인물을 가리키는 표현은 실제 인물명으로 통합하라.
- 한 인물이 성, 이름, 별칭, 호칭으로 다르게 등장하면 하나로 통합하라.
- 서로 다른 인물을 억지로 합치지 마라.
- 확신이 낮으면 별도 인물로 유지하라.
- confidence는 0.0~1.0 사이 숫자로 작성하라.

입력 인물 목록:
{json.dumps(character_candidates, ensure_ascii=False, indent=2)}

반환 형식:
{{
  "characters": [
    {{
      "canonical_name": "",
      "aliases": [""],
      "role": "",
      "description": "",
      "confidence": 0.95
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": "당신은 소설 인물명 정규화기이다. 반드시 JSON만 반환한다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    content = response.choices[0].message.content
    return json.loads(content)