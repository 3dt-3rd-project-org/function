import os
import tempfile
from azure.storage.blob import BlobServiceClient


def download_epub_from_blob(blob_name: str) -> str:
    conn_str = os.environ["BLOB_CONNECTION_STRING"]
    container_name = os.environ["BLOB_CONTAINER_NAME"]

    blob_service = BlobServiceClient.from_connection_string(conn_str)
    blob_client = blob_service.get_blob_client(
        container=container_name,
        blob=blob_name
    )

    temp_path = os.path.join(tempfile.gettempdir(), blob_name)

    with open(temp_path, "wb") as f:
        f.write(blob_client.download_blob().readall())

    return temp_path