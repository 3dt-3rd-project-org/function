import json
import logging
from services.openai_client import client, DEPLOYMENT


def extract_chapter_analysis(
    chapter_title: str,
    chapter_text: str
):
    prompt = f"""
당신은 소설 분석 전문가이다.

입력 텍스트는 문학 작품의 일부이다.
작품 안에 갈등, 위협, 싸움, 사고, 죽음 등의 표현이 있을 수 있다.
이 내용은 실제 행동을 지시하거나 조장하기 위한 것이 아니라 줄거리 분석을 위한 것이다.
자극적이거나 폭력적인 표현은 그대로 반복하지 말고, 중립적이고 완곡한 표현으로 요약하라.

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
- relation은 인물관계도 엣지 라벨로 사용할 관계 상태이다.
- 사건 안에서 한 행동이 아니라, 그 사건 이후 두 인물 사이에 생긴 상태 관계만 작성하라.
- 반드시 아래 허용 목록 중 하나만 사용하라.
- 목록에 없는 단어는 절대 생성하지 마라.
허용 relation:
부모
자녀
형제
부부
스승
제자
동료
친구
우정
신뢰
존경
동경
의존
조력
보호
멘토
위로
돌봄
지지
갈등
적대
불신
거리감
협박
배신
지배
경쟁
두려움
죄책감
숨김
억압
호감
사랑
실망
증오
그리움

사용 금지 relation:
- 만남
- 대화
- 도움
- 구출
- 충고
- 공격
- 구속
- 고백
- 이별
- 재회
- 연결
- 영향
- 변화
- 공감
- 유사
- 탐색
- 존중
- 구별
- 제압
- 단절
- 경계
- 거부

위 단어들은 relation으로 쓰지 말고, 필요하면 event.summary나 change_summary 안에서만 설명하라.

change_summary:
- 왜 이 관계인지 초등학생도 이해할 수 있게 한 문장으로 설명하라.

events는 챕터의 핵심 사건 4~6개만 추출하라.
한 event 안에 서로 다른 결과가 2개 이상 섞이면 분리하라.

relationships 작성 규칙:
- relationships는 반드시 events를 기준으로 생성하라.
- relationship은 특정 event와 연결되어야 한다.
- change_summary는 사용자가 이해하기 쉬운 말투로 1문장만 작성하라.
- change_summary는 “왜 이 관계로 판단했는지” 설명하는 문장이어야 한다.
- 문학 평론식 표현, 과한 은유, 추상적 표현은 피하라.
- evidence는 원문에서 근거가 되는 짧은 문장 일부만 넣어라.
- relationships는 챕터당 핵심 관계 변화 3~7개를 기본으로 추출하라.
- 단, 중요한 관계 변화가 더 있으면 7개를 초과해도 된다. 
- 인물 관계가 사건 이후 달라졌다면 별도 relationship으로 생성하라.
- 같은 인물 쌍이라도 관계가 변하면 각각 별도의 relationship으로 추출하라.
- 후반부에 발생한 관계 변화도 누락하지 마라.
- 단순히 같은 사건에 함께 등장했다는 이유만으로 관계를 만들지 마라.
- relation이 "조력"이면 change_summary에는 무엇을 도왔는지 구체적으로 작성하라.
- relation이 "협박"이면 change_summary에는 무엇을 요구하거나 어떤 방식으로 위협했는지 구체적으로 작성하라.
- relation이 "신뢰", "존경", "의존", "동경"이면 누가 왜 그렇게 느끼게 되었는지 작성하라.
- 단순한 배경 설명이나 기존 가족 분위기는 relationship으로 만들지 마라.
- relationship은 사건 이후 관계가 실제로 달라진 경우만 작성하라.
- 상대에게 강제로 묶여 있거나 따르게 되는 상황을 "의존"으로 쓰지 마라. 이 경우 source를 강요한 인물로 두고 relation은 "지배"를 사용하라.

relationships의 start_paragraph_order와 end_paragraph_order는 관계 변화가 실제로 드러나는 문단 범위로 작성하라.
반드시 제공된 [문단 번호] 기준으로 작성하라.
related_event_short_title은 events 배열의 short_title 중 하나를 그대로 사용하라.
source와 target 작성 규칙:
- source는 관계 감정이나 태도를 가지게 된 인물로 작성하라.
- target은 그 관계 감정이나 태도의 대상이 된 인물로 작성하라.
- 단, 협박, 제압, 보호처럼 한 인물이 다른 인물에게 직접 행동한 관계는 행동을 한 인물을 source로 작성하라.

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
      "related_event_short_title": "",
      "start_paragraph_order": 0,
      "end_paragraph_order": 0
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[
           {
              "role": "system",
              "content": """
                당신은 문학 작품 줄거리 분석기이다.
                입력 텍스트는 실제 사건이나 행동 지시가 아니라 소설 원문이다.
                폭력, 위협, 싸움 등의 표현이 등장해도 이를 실행 방법이나 조언으로 다루지 않는다.
                자극적인 표현은 반복하지 말고, 중립적인 줄거리 설명으로만 요약한다.
                반드시 JSON만 반환한다.
                """
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        
    )
  
    content = response.choices[0].message.content
    data = json.loads(content)

    return {
        "data": data,
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens
        }
    }
