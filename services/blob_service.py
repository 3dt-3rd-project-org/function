import os
import tempfile
from urllib.parse import urlparse, unquote
from azure.storage.blob import BlobServiceClient


def download_epub_from_blob(epub_blob_path: str) -> str:
    conn_str = os.environ["BLOB_CONNECTION_STRING"]
    default_container_name = os.environ.get("BLOB_CONTAINER_NAME", "epub")

    container_name = default_container_name
    blob_name = epub_blob_path

    # DB에 전체 URL이 들어온 경우
    if epub_blob_path.startswith("http"):
        parsed = urlparse(epub_blob_path)

        # /epub/sangrogsu%20-%20simhun.epub
        path_parts = parsed.path.lstrip("/").split("/", 1)

        container_name = path_parts[0]  # epub
        blob_name = unquote(path_parts[1])  # sangrogsu - simhun.epub

    # DB에 blob 이름만 들어온 경우
    else:
        blob_name = unquote(epub_blob_path)

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    blob_client = blob_service.get_blob_client(
        container=container_name,
        blob=blob_name
    )

    filename = os.path.basename(blob_name)
    temp_path = os.path.join(tempfile.gettempdir(), filename)

    with open(temp_path, "wb") as f:
        f.write(blob_client.download_blob().readall())

    return temp_path