"""조항 목록을 임베딩해서 도커 Postgres에 넣는다.

본문 앞에 passage: 를 붙인다. 연혁 목록은 벡터에 넣지 않고 jsonb 컬럼에 둔다.
PDF부터 하려면 pipeline.py 를 실행한다. 이미 만든 chunk.json만 넣을 때는 이 파일을 실행한다.

  docker compose up -d
  $env:LLAMA_BIN="llama-server.exe 경로"
  $env:GGUF="Nemotron-3-Embed-8B-Q6_K.gguf 경로"
  python embed.py
"""

import json
import os

from psycopg.types.json import Json

from common import CHUNKS, DIM, PASSAGE, connect, embed_texts, ensure_server

BATCH = int(os.environ.get("EMBED_BATCH", "4"))


def load_chunks():
    with open(CHUNKS, encoding="utf-8") as source:
        return json.load(source)


def column_types(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public'
              AND c.relname = 'regulation_chunk'
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        )
        return dict(cur.fetchall())


def ensure_table(conn):
    """vector(4096) 테이블을 만든다. 차원이 다른 예전 테이블이면 멈추고 알린다."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()
    columns = column_types(conn)
    if not columns:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE regulation_chunk (
                    id integer PRIMARY KEY,
                    "규정명" text NOT NULL,
                    "규정번호" text NOT NULL,
                    "조" text NOT NULL,
                    page integer,
                    content text NOT NULL,
                    "연혁" jsonb NOT NULL,
                    embedding vector({DIM}) NOT NULL
                )
                """
            )
        conn.commit()
        return
    embedding = columns.get("embedding", "")
    if embedding != f"vector({DIM})" or "연혁" not in columns:
        raise SystemExit(
            "regulation_chunk 테이블의 모양이 다릅니다. "
            "기존 벡터를 지울 거면 DROP TABLE regulation_chunk 를 실행한 뒤 다시 적재하세요. "
            f"(embedding={embedding or '없음'}, 연혁={'있음' if '연혁' in columns else '없음'})"
        )


def upsert(conn, rows):
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO regulation_chunk
                (id, "규정명", "규정번호", "조", page, content, "연혁", embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                "규정명" = EXCLUDED."규정명",
                "규정번호" = EXCLUDED."규정번호",
                "조" = EXCLUDED."조",
                page = EXCLUDED.page,
                content = EXCLUDED.content,
                "연혁" = EXCLUDED."연혁",
                embedding = EXCLUDED.embedding
            """,
            rows,
        )
    conn.commit()


def store(chunks):
    """조항 목록을 임베딩해 regulation_chunk에 넣는다."""
    ensure_server()
    conn = connect()
    ensure_table(conn)
    with conn.cursor() as cur:
        cur.execute("DROP INDEX IF EXISTS regulation_chunk_embedding_hnsw")
    conn.commit()

    total = len(chunks)
    for start in range(0, total, BATCH):
        batch = chunks[start:start + BATCH]
        vectors = embed_texts([PASSAGE + chunk["text"] for chunk in batch])
        rows = []
        for offset, (chunk, vector) in enumerate(zip(batch, vectors)):
            meta = chunk["metadata"]
            rows.append((
                start + offset,
                meta["규정명"],
                meta["규정번호"],
                meta["조"],
                meta["page"],
                chunk["text"],
                Json(meta.get("연혁", [])),
                vector,
            ))
        upsert(conn, rows)
        print(f"적재 {min(start + BATCH, total)}/{total}", flush=True)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM regulation_chunk WHERE id >= %s", (total,))
        cur.execute(
            """
            CREATE INDEX regulation_chunk_embedding_hnsw
            ON regulation_chunk
            USING hnsw (embedding vector_cosine_ops)
            """
        )
    conn.commit()
    conn.close()
    print(f"완료. {total}개 조항을 넣었습니다.", flush=True)


def main():
    store(load_chunks())


if __name__ == "__main__":
    main()
