
import os

EMBEDDINGS_HEADERS = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + os.getenv("OPENAI_API_KEY"),
    }
EMBEDDINGS_ENDPOINT = "https://api.openai.com/v1/embeddings"


bertseg_configs = {
    "SENTENCE_COMPARISON_WINDOW": 2,
    "SMOOTHING_PASSES": 2,
    "SMOOTHING_WINDOW": 1,
    "EMBEDDINGS_HEADERS": EMBEDDINGS_HEADERS,
    "EMBEDDINGS_ENDPOINT": EMBEDDINGS_ENDPOINT,
}

