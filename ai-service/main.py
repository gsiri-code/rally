import os

from dotenv import load_dotenv
from qdrant_client import QdrantClient


def main():
    load_dotenv()

    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")

    if not qdrant_url or not qdrant_api_key:
        raise RuntimeError(
            "Missing QDRANT_URL or QDRANT_API_KEY. Add them to your .env file."
        )

    qdrant_client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    print(qdrant_client.get_collections())


if __name__ == "__main__":
    main()
