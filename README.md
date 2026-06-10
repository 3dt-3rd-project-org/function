# ReadPoint Azure Function Pipeline

ReadPoint는 EPUB 소설을 문단 단위로 분해한 뒤, Azure OpenAI를 이용해 인물, 사건, 관계 변화 데이터를 추출하고 PostgreSQL 및 Neo4j에 저장하는 소설 지식그래프 생성 파이프라인입니다. 또한 사용자가 오래 전 읽던 위치로 돌아왔을 때 바로 이어 읽을 수 있도록 사건 단위의 `progress_summary` 리캡을 미리 생성합니다.

## 1. 프로젝트 개요

이 Function App은 ReadPoint 데이터 처리 파이프라인의 백엔드 처리 계층입니다.

주요 역할은 다음과 같습니다.

- EPUB 파일 다운로드 및 챕터/문단 분리
- 챕터별 LLM 분석을 통한 인물, 사건, 관계 변화 추출
- 인물명 정규화
- PostgreSQL 테이블 저장
- 사건/인물/관계 중요도 보정
- Neo4j Graph DB 마이그레이션
- 이어읽기용 사건 단위 리캡 생성

전체 처리 흐름은 다음과 같습니다.

```text
EPUB Blob
  ↓
chapter_split
  ↓
openai_extract_chapter  ← ADF ForEach 병렬/반복 호출
  ↓
normalize_characters
  ↓
save_normalized_analysis
  ↓
book_graph_refine
  ↓
migrate_graph
  ↓
generate_progress_summary_event  ← ADF ForEach 순차 호출
```

## 2. 기술 스택

| 구분 | 기술 |
|---|---|
| Runtime | Azure Functions Python |
| Language | Python 3.11 |
| Orchestration | Azure Data Factory |
| LLM | Azure OpenAI |
| Relational DB | Azure Database for PostgreSQL |
| Graph DB | Neo4j |
| File Storage | Azure Blob Storage |
| EPUB Parser | ebooklib, BeautifulSoup4, lxml |
| Deployment | GitHub Actions |

## 3. 폴더 구조

```text
function-main/
├─ function_app.py
├─ host.json
├─ requirements.txt
├─ services/
│  ├─ blob_service.py
│  ├─ book_refine_service.py
│  ├─ character_normalize_service.py
│  ├─ db_service.py
│  ├─ epub_parser.py
│  ├─ extract_service.py
│  ├─ grapdb_service.py
│  ├─ normalize_service.py
│  ├─ openai_client.py
│  ├─ openai_service.py
│  ├─ progress_summary_service.py
│  └─ save_normalized_service.py
└─ .github/
   └─ workflows/
      └─ main_functions-pipeline.yml
```

## 4. Azure Function API 목록

### 4.1 `chapter_split`

EPUB 파일을 Blob Storage에서 다운로드한 뒤 챕터와 문단으로 분리하여 PostgreSQL에 저장합니다.

```http
POST /api/chapter_split
```

요청 예시:

```json
{
  "books_id": 1
}
```

처리 내용:

- `books` 테이블에서 `epub_blob_path` 조회
- Blob Storage에서 EPUB 다운로드
- EPUB 파싱
- `chapter`, `paragraph` 테이블 저장

---

### 4.2 `openai_extract_chapter`

특정 챕터의 문단을 가져와 Azure OpenAI로 인물, 사건, 관계 변화를 추출하고 `chapter_analysis_raw`에 저장합니다.

```http
POST /api/openai_extract_chapter
```

요청 예시:

```json
{
  "books_id": 1,
  "chapter_id": 7
}
```

특징:

- 책 전체를 한 번에 처리하지 않음
- ADF Lookup + ForEach 구조로 챕터별 반복 호출
- 긴 소설 처리 시 Function timeout을 줄이기 위한 구조

---

### 4.3 `normalize_characters`

`chapter_analysis_raw.raw_json`에 들어 있는 인물 후보를 수집하고, 동일 인물의 다양한 표현을 대표 이름으로 정규화합니다.

```http
POST /api/normalize_characters
```

요청 예시:

```json
{
  "books_id": 1
}
```

저장 대상:

- `character_alias_map`

---

### 4.4 `save_normalized_analysis`

정규화된 인물명을 기준으로 인물, 사건, 사건 참여 인물, 관계 변화 데이터를 PostgreSQL에 저장합니다.

```http
POST /api/save_normalized_analysis
```

요청 예시:

```json
{
  "books_id": 1
}
```

저장 대상:

- `character`
- `event`
- `event_character`
- `relationship_change`

---

### 4.5 `book_graph_refine`

저장된 인물, 사건, 관계 변화 데이터를 책 전체 관점에서 보정합니다.

```http
POST /api/book_graph_refine
```

요청 예시:

```json
{
  "books_id": 1
}
```

주요 처리:

- 인물 중요도 보정
- 사건 중요도 및 핵심 사건 여부 보정
- 관계 변화 중요도 및 핵심 관계 여부 보정

---

### 4.6 `migrate_graph`

PostgreSQL에 저장된 인물, 사건, 관계 데이터를 Neo4j Graph DB로 마이그레이션합니다.

```http
POST /api/migrate_graph
```

요청 예시:

```json
{
  "books_id": 1
}
```

처리 내용:

- PostgreSQL에서 챕터별 raw 분석 결과 조회
- Neo4j에 Book, Chapter, Character, Event, Relationship 관련 노드/관계 저장

---

### 4.7 `generate_progress_summary_event`

특정 사건 기준으로 이어읽기용 3줄 리캡을 생성하고 `progress_summary`에 저장합니다.

```http
POST /api/generate_progress_summary_event
```

요청 예시:

```json
{
  "books_id": 1,
  "event_id": 53
}
```

특징:

- ADF ForEach에서 순차 호출해야 함
- 이전 사건의 `cumulative_summary_text`를 DB에서 조회
- 현재 사건과 이전 누적 상태를 함께 사용하여 새 리캡 생성
- 사용자 노출용 `summary_3line`과 LLM 내부용 `cumulative_summary_text`를 저장

## 5. Azure Data Factory 파이프라인 구조

### 5.1 챕터 분석 파이프라인

```text
chapter_split
  ↓
get_chapters Lookup
  ↓
ForEach
  └─ openai_extract_chapter
  ↓
normalize_characters
  ↓
save_normalized_analysis
  ↓
book_graph_refine
  ↓
migrate_graph
```

`get_chapters` Lookup 예시:

```sql
SELECT chapter_id
FROM chapter
WHERE books_id = @{pipeline().parameters.books_id}
ORDER BY chapter_order;
```

ForEach Body 예시:

```json
{
  "books_id": "@{pipeline().parameters.books_id}",
  "chapter_id": "@{item().chapter_id}"
}
```

### 5.2 이어읽기 요약 생성 파이프라인

```text
get_progress_events Lookup
  ↓
ForEach 순차 실행
  └─ generate_progress_summary_event
```

`get_progress_events` Lookup 예시:

```sql
SELECT event_id
FROM event
WHERE books_id = @{pipeline().parameters.books_id}
  AND importance_score >= 0.6
ORDER BY chapter_id, event_order, event_id;
```

ForEach Body 예시:

```json
{
  "books_id": "@{pipeline().parameters.books_id}",
  "event_id": "@{item().event_id}"
}
```

중요:

- `generate_progress_summary_event`는 반드시 순차 실행해야 합니다.
- 병렬 실행 시 이전 사건의 `cumulative_summary_text`가 저장되기 전에 다음 사건이 실행되어 요약 흐름이 깨질 수 있습니다.

## 6. 주요 데이터베이스 테이블

| 테이블 | 목적 |
|---|---|
| `books` | 도서 메타데이터 및 EPUB Blob 경로 저장 |
| `chapter` | 도서별 챕터 정보 저장 |
| `paragraph` | EPUB에서 추출한 문단 저장 |
| `chapter_analysis_raw` | 챕터별 LLM 원본 분석 JSON 저장 |
| `character_alias_map` | 인물 별칭과 대표 이름 매핑 |
| `character` | 정규화된 등장인물 저장 |
| `event` | 소설 내 사건 저장 |
| `event_character` | 사건과 인물의 다대다 관계 저장 |
| `relationship_change` | 인물 간 관계 변화 저장 |
| `progress_summary` | 이어읽기용 사건 단위 리캡 저장 |

## 7. 환경 변수

로컬 실행 및 Azure Function App 설정에 아래 환경 변수가 필요합니다.

### PostgreSQL

```text
PGHOST
PGPORT
PGDATABASE
PGUSER
PGPASSWORD
```

### Azure Blob Storage

```text
BLOB_CONNECTION_STRING
BLOB_CONTAINER_NAME
```

`BLOB_CONTAINER_NAME`은 없으면 기본값으로 `epub`을 사용합니다.

### Azure OpenAI

```text
AZURE_OPENAI_ENDPOINT
AZURE_OPENAI_API_KEY
AZURE_OPENAI_API_VERSION
AZURE_OPENAI_DEPLOYMENT
```

### Neo4j

```text
NEO4J_URI
NEO4J_USER
NEO4J_PASSWORD
```

## 8. 로컬 실행 방법

### 8.1 가상환경 생성 및 활성화

```powershell
python -m venv .venv
.venv\Scripts\activate
```

### 8.2 패키지 설치

```powershell
pip install -r requirements.txt
```

### 8.3 로컬 설정

`local.settings.json`을 생성하고 환경 변수를 등록합니다.

예시:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "PGHOST": "...",
    "PGPORT": "...",
    "PGDATABASE": "...",
    "PGUSER": "...",
    "PGPASSWORD": "...",
    "BLOB_CONNECTION_STRING": "...",
    "BLOB_CONTAINER_NAME": "epub",
    "AZURE_OPENAI_ENDPOINT": "...",
    "AZURE_OPENAI_API_KEY": "...",
    "AZURE_OPENAI_API_VERSION": "2024-12-01-preview",
    "AZURE_OPENAI_DEPLOYMENT": "...",
    "NEO4J_URI": "...",
    "NEO4J_USER": "...",
    "NEO4J_PASSWORD": "..."
  }
}
```

### 8.4 Function App 실행

```powershell
func start
```

정상 실행 시 다음과 같은 함수 목록이 표시됩니다.

```text
book_graph_refine
chapter_split
generate_progress_summary_event
migrate_graph_endpoint
normalize_characters
openai_extract_chapter
save_normalized_analysis
```

## 9. API 테스트 예시

### 챕터/문단 분리

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:7071/api/chapter_split" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"books_id":1}'
```

### 챕터별 LLM 분석

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:7071/api/openai_extract_chapter" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"books_id":1,"chapter_id":7}'
```

### 이어읽기 요약 생성

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:7071/api/generate_progress_summary_event" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"books_id":1,"event_id":53}'
```

## 10. 배포 방법

이 저장소는 GitHub Actions를 통해 Azure Function App에 자동 배포됩니다.

배포 대상:

```text
functions-pipeline
```

배포 트리거:

```text
main 브랜치 push
workflow_dispatch 수동 실행
```

수동 배포 명령 예시:

```powershell
func azure functionapp publish functions-pipeline --python --build remote
```

## 11. 운영 시 주의사항

### 11.1 챕터 분석은 챕터 단위로 실행

기존의 책 전체 분석 방식은 Function timeout 위험이 있으므로 사용하지 않습니다.

```text
openai_extract 전체 실행 ❌
openai_extract_chapter 반복 실행 ✅
```

### 11.2 progress summary는 반드시 순차 실행

`progress_summary`는 이전 사건의 누적 요약을 읽어 다음 사건 요약을 생성합니다.

```text
ForEach 병렬 실행 ❌
ForEach 순차 실행 ✅
```

### 11.3 PostgreSQL 삭제 순서 주의

`paragraph`, `event`, `relationship_change` 등은 FK 관계가 있으므로 재처리 시 참조하는 자식 테이블부터 삭제해야 합니다.

권장 삭제 순서 예시:

```sql
DELETE FROM progress_summary WHERE books_id = 1;
DELETE FROM relationship_change WHERE books_id = 1;
DELETE FROM event_character
WHERE event_id IN (SELECT event_id FROM event WHERE books_id = 1);
DELETE FROM event WHERE books_id = 1;
DELETE FROM character WHERE books_id = 1;
DELETE FROM character_alias_map WHERE books_id = 1;
DELETE FROM chapter_analysis_raw WHERE books_id = 1;
DELETE FROM paragraph WHERE books_id = 1;
DELETE FROM chapter WHERE books_id = 1;
```


