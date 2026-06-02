import json
import logging
import azure.functions as func

from services.db_service import (
    get_conn,
    get_book_by_id,
    save_chapters_and_paragraphs
)
from services.blob_service import download_epub_from_blob
from services.epub_parser import parse_epub
from services.extract_service import run_openai_extract

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



