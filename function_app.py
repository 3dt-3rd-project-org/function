import json
import logging
import azure.functions as func
import azure.durable_functions as df

from services.db_service import (
    get_conn,
    get_book_by_id,
    save_chapters_and_paragraphs,
    fetch_and_transform_chapter_raw,
)

from services.blob_service import download_epub_from_blob
from services.epub_parser import parse_epub
from services.extract_service import run_openai_extract_chapter
from services.normalize_service import run_normalize_characters
from services.save_normalized_service import run_save_normalized_analysis
from services.grapdb_service import insert_graph_data
from services.book_refine_service import run_book_graph_refine
from services.progress_summary_service import generate_progress_summary_for_event


app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)

# bronze layer

## 챕터, 문단 분리
@app.route(route="chapter_split", methods=["POST"])
def chapter_split(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("chapter_split function called")

    try:
        body = req.get_json()
        books_id = body.get("books_id")

        if books_id is None:
            return func.HttpResponse(
                json.dumps({"error": "books_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        books_id = int(books_id)

        conn = get_conn()

        try:
            with conn:
                book = get_book_by_id(conn, books_id)

                if book is None:
                    return func.HttpResponse(
                        json.dumps({"error": f"books_id={books_id} not found"}, ensure_ascii=False),
                        status_code=404,
                        mimetype="application/json"
                    )

                _, title, author, epub_blob_path = book

                if not epub_blob_path:
                    return func.HttpResponse(
                        json.dumps({"error": "epub_blob_path is empty"}, ensure_ascii=False),
                        status_code=400,
                        mimetype="application/json"
                    )

                local_epub_path = download_epub_from_blob(epub_blob_path)
                rows = parse_epub(local_epub_path)

                if not rows:
                    return func.HttpResponse(
                        json.dumps({"error": "No chapter/paragraph extracted"}, ensure_ascii=False),
                        status_code=400,
                        mimetype="application/json"
                    )

                counts = save_chapters_and_paragraphs(conn, books_id, rows)

                result = {
                    "status": "success",
                    "message": "chapter_split completed",
                    "books_id": books_id,
                    "title": title,
                    "author": author,
                    "epub_blob_path": epub_blob_path,
                    "chapter_count": counts["chapter_count"],
                    "paragraph_count": counts["paragraph_count"]
                }

        finally:
            conn.close()

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("chapter_split failed")

        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )
    


# silver layer

## 인물/사건/관계 추출
@app.route(route="openai_extract_chapter", methods=["POST"])
def openai_extract_chapter(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("openai_extract_chapter function called")

    try:
        body = req.get_json()
        books_id = body.get("books_id")
        chapter_id = body.get("chapter_id")

        if books_id is None:
            return func.HttpResponse(
                json.dumps({"error": "books_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        if chapter_id is None:
            return func.HttpResponse(
                json.dumps({"error": "chapter_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        books_id = int(books_id)
        chapter_id = int(chapter_id)

        conn = get_conn()

        try:
            with conn:
                result = run_openai_extract_chapter(conn, books_id, chapter_id)
        finally:
            conn.close()

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("openai_extract_chapter failed")

        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )
    

## 인물 정규화
@app.route(route="normalize_characters", methods=["POST"])
def normalize_characters(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("normalize_characters function called")

    try:
        body = req.get_json()
        books_id = body.get("books_id")

        if books_id is None:
            return func.HttpResponse(
                json.dumps({"error": "books_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        books_id = int(books_id)

        conn = get_conn()

        try:
            with conn:
                result = run_normalize_characters(conn, books_id)
        finally:
            conn.close()

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("normalize_characters failed")

        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )


# GOLD LAYER

## 정규화 된 인물 사용하여 POSTGRESQL 인물/사건/사건참여 인물/관게변화 테이블에 저장 
@app.route(route="save_normalized_analysis", methods=["POST"])
def save_normalized_analysis(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("save_normalized_analysis function called")

    try:
        body = req.get_json()
        books_id = body.get("books_id")

        if books_id is None:
            return func.HttpResponse(
                json.dumps({"error": "books_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        books_id = int(books_id)

        conn = get_conn()

        try:
            with conn:
                result = run_save_normalized_analysis(conn, books_id)
        finally:
            conn.close()

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("save_normalized_analysis failed")

        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )



## 인물/사건/관계변화 테이블 중요도 선정
@app.route(route="book_graph_refine", methods=["POST"])
def book_graph_refine(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("book_graph_refine function called")

    try:
        body = req.get_json()
        books_id = body.get("books_id")

        if books_id is None:
            return func.HttpResponse(
                json.dumps({"error": "books_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        books_id = int(books_id)

        conn = get_conn()

        try:
            with conn:
                result = run_book_graph_refine(conn, books_id)
        finally:
            conn.close()

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("book_graph_refine failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )
    
## 비동기용 함수
@app.route(route="book_graph_refine_start", methods=["POST"])
@app.durable_client_input(client_name="client")
async def book_graph_refine_start(req: func.HttpRequest, client):
    logging.info("book_graph_refine_start function called")

    try:
        body = req.get_json()
        books_id = body.get("books_id")

        if books_id is None:
            return func.HttpResponse(
                json.dumps({"error": "books_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        books_id = int(books_id)

        instance_id = await client.start_new(
            "book_graph_refine_orchestrator",
            None,
            {"books_id": books_id}
        )

        return func.HttpResponse(
            json.dumps({
                "status": "accepted",
                "message": "book_graph_refine started",
                "books_id": books_id,
                "instance_id": instance_id
            }, ensure_ascii=False),
            status_code=202,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("book_graph_refine_start failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )


@app.orchestration_trigger(context_name="context")
def book_graph_refine_orchestrator(context: df.DurableOrchestrationContext):
    input_data = context.get_input()

    result = yield context.call_activity(
        "book_graph_refine_activity",
        input_data
    )

    return result


@app.activity_trigger(input_name="input_data")
def book_graph_refine_activity(input_data: dict):
    books_id = int(input_data["books_id"])

    logging.info(f"book_graph_refine_activity started books_id={books_id}")

    conn = get_conn()

    try:
        with conn:
            result = run_book_graph_refine(conn, books_id)

        logging.info(f"book_graph_refine_activity completed books_id={books_id}")
        return result

    except Exception:
        logging.exception("book_graph_refine_activity failed")
        raise

    finally:
        conn.close()



@app.route(route="book_graph_refine_status", methods=["POST"])
@app.durable_client_input(client_name="client")
async def book_graph_refine_status(req: func.HttpRequest, client):
    logging.info("book_graph_refine_status function called")

    try:
        body = req.get_json()
        instance_id = body.get("instance_id")

        if not instance_id:
            return func.HttpResponse(
                json.dumps({"error": "instance_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )


        status = await client.get_status(instance_id)

        if status is None:
            return func.HttpResponse(
                json.dumps({
                    "status": "not_found",
                    "instance_id": instance_id
                }, ensure_ascii=False),
                status_code=404,
                mimetype="application/json"
            )

        return func.HttpResponse(
            json.dumps({
                "instance_id": instance_id,
                "runtimeStatus": status.runtime_status.name,
                "createdTime": status.created_time.isoformat() if status.created_time else None,
                "lastUpdatedTime": status.last_updated_time.isoformat() if status.last_updated_time else None,
                "output": status.output
            }, ensure_ascii=False, default=str),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("book_graph_refine_status failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )



## NEO4J GRAPH DB 저장
@app.route(route="migrate_graph", methods=["POST"])
def migrate_graph_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("migrate_graph function called")

    try:
        try:
            req_body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({"error": "올바른 JSON 형식이 아닙니다."}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json",
            )

        books_id = req_body.get("books_id")

        if books_id is None:
            return func.HttpResponse(
                json.dumps({"error": "books_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json",
            )

        books_id = int(books_id)

        logging.info(f"[PostgreSQL] books_id={books_id} graph data fetch start")

        with get_conn() as conn:
            postgres_data = fetch_and_transform_chapter_raw(
                conn,
                books_id
            )

        if not postgres_data:
            return func.HttpResponse(
                json.dumps({"error": f"books_id={books_id} graph data not found"}, ensure_ascii=False),
                status_code=404,
                mimetype="application/json",
            )

        logging.info(f"[Neo4j] books_id={books_id} graph insert start")

        success = insert_graph_data(postgres_data)

        if success:
            return func.HttpResponse(
                json.dumps(
                    {
                        "status": "success",
                        "message": f"books_id={books_id} Neo4j migration completed"
                    },
                    ensure_ascii=False
                ),
                status_code=200,
                mimetype="application/json",
            )

        return func.HttpResponse(
            json.dumps({"error": "Neo4j insert failed"}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json",
        )

    except Exception as e:
        logging.exception("migrate_graph failed")

        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json",
        )

    



## 요약본 생성
@app.route(route="generate_progress_summary_event", methods=["POST"])
def generate_progress_summary_event(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("generate_progress_summary_event function called")

    try:
        body = req.get_json()
        books_id = body.get("books_id")
        event_id = body.get("event_id")

        if books_id is None:
            return func.HttpResponse(
                json.dumps({"error": "books_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        if event_id is None:
            return func.HttpResponse(
                json.dumps({"error": "event_id is required"}, ensure_ascii=False),
                status_code=400,
                mimetype="application/json"
            )

        books_id = int(books_id)
        event_id = int(event_id)

        conn = get_conn()

        try:
            with conn:
                result = generate_progress_summary_for_event(conn, books_id, event_id)
        finally:
            conn.close()

        status_code = 200 if result.get("status") == "success" else 404

        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=status_code,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("generate_progress_summary_event failed")

        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )