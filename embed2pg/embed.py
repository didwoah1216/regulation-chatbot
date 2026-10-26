import json
import os

import psycopg
from ollama import Client
from pgvector.psycopg import register_vector

# md2chunk-json/chunk.py가 만든 조각. 이 스크립트는 벡터 파일을 만들지 않고 PostgreSQL에 행으로 넣는다.
CHUNKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../md2chunk-json/chunk.json")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
DIM = 1024  # bge-m3 밀집 벡터 차원
BATCH = 8
# ollama 패키지는 로컬에 떠 있는 Ollama 서버로 요청을 보내는 클라이언트다.
ollama = Client(host=OLLAMA)


def load_chunks(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def embed_batch(texts):
    """로컬 Ollama에 조각 본문을 보내 1024차원 벡터를 받는다."""
    try:
        result = ollama.embed(model=MODEL, input=texts)
    except Exception as e:
        raise SystemExit(f"Ollama에 연결하지 못했습니다. {OLLAMA} 에서 {MODEL} 이 떠 있는지 확인하세요. ({e})")
    vectors = result.embeddings
    if len(vectors) != len(texts):
        raise SystemExit("Ollama 응답의 벡터 개수가 입력과 다릅니다.")
    if len(vectors[0]) != DIM:
        raise SystemExit(f"벡터 차원이 {len(vectors[0])}입니다. bge-m3의 {DIM}차원이 아닙니다.")
    return vectors


def ensure_table(conn):
    """pgvector 확장과 규정 조각 테이블을 만든다. 이미 있으면 그대로 둔다."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS regulation_chunk (
                id integer PRIMARY KEY,
                "규정명" text NOT NULL,
                "규정번호" text NOT NULL,
                "조" text NOT NULL,
                page integer NOT NULL,
                content text NOT NULL,
                embedding vector(1024) NOT NULL
            )
            """
        )
    conn.commit()


def upsert(conn, rows):
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO regulation_chunk
                (id, "규정명", "규정번호", "조", page, content, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                "규정명" = EXCLUDED."규정명",
                "규정번호" = EXCLUDED."규정번호",
                "조" = EXCLUDED."조",
                page = EXCLUDED.page,
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding
            """,
            rows,
        )
    conn.commit()


def finish(conn, count):
    """이번 실행에서 빠진 옛 행을 지우고, 코사인 거리용 인덱스를 만든다."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM regulation_chunk WHERE id >= %s", (count,))
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS regulation_chunk_embedding_hnsw
            ON regulation_chunk USING hnsw (embedding vector_cosine_ops)
            """
        )
    conn.commit()


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL이 없습니다. 예: postgresql://user:pass@localhost:5432/regulation")

    chunks = load_chunks(CHUNKS)
    with psycopg.connect(url) as conn:
        register_vector(conn)
        ensure_table(conn)
        done = 0
        for start in range(0, len(chunks), BATCH):
            batch = chunks[start:start + BATCH]
            vectors = embed_batch([item["text"] for item in batch])
            rows = []
            for offset, (item, vector) in enumerate(zip(batch, vectors)):
                meta = item["metadata"]
                rows.append((
                    start + offset,
                    meta["규정명"],
                    meta["규정번호"],
                    meta["조"],
                    meta["page"],
                    item["text"],
                    vector,
                ))
            upsert(conn, rows)
            done += len(rows)
            print(f"저장 {done}/{len(chunks)}", flush=True)
        finish(conn, len(chunks))
    print(f"regulation_chunk {len(chunks)}행", flush=True)


if __name__ == "__main__":
    main()
