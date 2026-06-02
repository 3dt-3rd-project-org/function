import json

from services.openai_client import client, DEPLOYMENT


def extract_chapter_analysis(
    chapter_title: str,
    chapter_text: str
):
    prompt = f"""
당신은 소설 분석 전문가이다.

챕터 제목:
{chapter_title}

챕터 내용:
{chapter_text}

반드시 JSON만 반환하라.
JSON 외 설명, 마크다운, 코드블록은 절대 쓰지 마라.
모든 출력값은 한국어로 작성하라.
- 문학 비평가처럼 쓰지 마라.
- 논문체, 평론체, 은유적 표현을 사용하지 마라.
- 중학생도 이해할 수 있는 쉬운 한국어를 사용하라.
- 모든 출력은 사실 설명 형태로 작성하라.

character.role은 인물의 신분이나 위치를 작성하라.

예:
주인공
전학생
학생
아버지
어머니
교사

조력자, 협박자, 피해자 같은 표현은 사용하지 마라.

character.description:
- 인물이 누구인지 한 문장으로 설명하라.
- "구원자", "상징", "유혹자", "화신" 같은 해석적 표현을 사용하지 마라.

event.summary:
- 실제로 발생한 사건만 설명하라.
- "세계관을 뒤흔든 만남" 같은 감상 표현을 사용하지 마라.

event.short_title:
- 사건 제목처럼 짧게 작성하라.
- 5~15자 이내로 작성하라.
- 명사형 또는 짧은 제목 형태로 작성하라.
- 예: 데미안의 등장, 카인 해석, 크로머의 협박, 데미안의 개입, 싱클레어의 고백

role_in_event:
- 사건에서 수행한 역할만 작성하라.
- 예:
주인공
협박자
피해자
조력자
부모
목격자
친구

relation:
- 반드시 한 단어로 작성하라.
- 예:
조력
협박
보호
갈등
화해
신뢰
의존
경계

change_summary:
- 왜 이 관계인지 초등학생도 이해할 수 있게 한 문장으로 설명하라.
relationships 작성 규칙:
- relation은 그래프 엣지 라벨로 사용할 짧은 단어로 작성하라.
- relation은 2~6글자 정도의 명사형 또는 짧은 관계명으로 작성하라.
- 예: 협박, 조력, 보호, 갈등, 의존, 거리두기, 화해, 제압, 신뢰
- relation에 긴 문장이나 여러 관계를 한꺼번에 넣지 마라.
- change_summary는 사용자가 이해하기 쉬운 말투로 1문장만 작성하라.
- change_summary는 “왜 이 관계로 판단했는지” 설명하는 문장이어야 한다.
- 문학 평론식 표현, 과한 은유, 추상적 표현은 피하라.
- evidence는 원문에서 근거가 되는 짧은 문장 일부만 넣어라.

related_event_summary:
- 반드시 events 배열에 있는 short_title 중 하나를 그대로 사용하라.
- 새 문장을 만들지 마라.

추출 기준:
- characters는 서사 진행에 중요한 인물만 추출하라.
- characters는 최대 7명까지만 추출하라.
- 다음은 character가 아니다.
- 개념
- 철학적 사상
- 감정
- 본능
- 자연
- 신성
- 상징
- 동물 예시
- 추상적 존재
- 원문에 등장하는 호칭을 우선 사용하라.
- 동일 인물의 여러 호칭은 하나로 통일하라.
- 인물명은 원문 번역명 기준의 한국어 표기로 작성하라.
- events는 챕터의 핵심 사건 3~4개만 추출하라.
- 사건은 너무 잘게 쪼개지 말고 원인-갈등-결과가 이어지는 단위로 묶어라.
- relationships는 핵심 인물 사이의 관계 변화만 2~5개 추출하라.
- evidence는 원문에서 근거가 되는 문장 일부를 넣어라.
- start_paragraph_order와 end_paragraph_order는 제공된 [문단 번호] 기준으로 작성하라.

반환 형식:

{{
  "characters": [
    {{
      "name": "",
      "role": "",
      "description": ""
    }}
  ],
  "events": [
    {{
      "short_title": "",
      "summary": "",
      "evidence": "",
      "start_paragraph_order": 0,
      "end_paragraph_order": 0,
      "characters": [
        {{
          "name": "",
          "role_in_event": ""
        }}
      ]
    }}
  ],
  "relationships": [
    {{
      "source": "",
      "target": "",
      "relation": "",
      "change_summary": "",
      "evidence": "",
      "related_event_summary": ""
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": "당신은 소설 분석기이다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
    )

    content = response.choices[0].message.content

    return json.loads(content)