import json
import logging
import azure.functions as func

from services.db_service import (
    get_conn,
    get_book_by_id,
    save_chapters_and_paragraphs,
    fetch_and_transform_chapter_raw,
)

from services.blob_service import download_epub_from_blob
from services.epub_parser import parse_epub
from services.extract_service import run_openai_extract
from services.normalize_service import run_normalize_characters
from services.save_normalized_service import run_save_normalized_analysis
from services.grapdb_service import insert_graph_data

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# bronze layer
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

@app.route(route="openai_extract", methods=["POST"])
def openai_extract(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("openai_extract function called")

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
                result = run_openai_extract(conn, books_id)

        finally:
            conn.close()

        return func.HttpResponse(
            json.dumps({
                "status": "success",
                "message": "openai_extract completed",
                "books_id": books_id,
                **result
            }, ensure_ascii=False),
            status_code=200,
            mimetype="application/json"
        )

    except Exception as e:
        logging.exception("openai_extract failed")

        return func.HttpResponse(
            json.dumps({"error": str(e)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json"
        )


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