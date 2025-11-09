from typing import List
from openai import OpenAI
import os

def embed_texts(texts: List[str], model: str = "text-embedding-3-small", batch: int = 32) -> List[List[float]]:
    client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL"), timeout=30.0)
    out = []
    for i in range(0, len(texts), batch):
        part = texts[i:i+batch]
        r = client.embeddings.create(model=model, input=part)
        out.extend([d.embedding for d in r.data])
    return out
