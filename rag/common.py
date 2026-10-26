"""적재와 질문이 같이 쓰는 접속과 임베딩.

벡터는 Nemotron-3-Embed-8B-Q6_K.gguf 하나에서만 만든다.
문서는 passage:, 질문은 query: 를 붙이고, 풀링은 mean 이다.
차원은 4096이다. 답변 모델 벡터와 섞지 않는다.
"""

import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import psycopg
from pgvector.psycopg import register_vector

CHUNKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../md2chunk-json/chunk.json")
DIM = 4096
PASSAGE = "passage: "
QUERY = "query: "
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://regulation:regulation@localhost:5432/regulation",
)
LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8081").rstrip("/")
# 가장 긴 안전수칙 조각이 약 7천 자라, 기본 문맥은 16384로 둔다. 메모리가 모자라면 LLAMA_CTX=8192.
LLAMA_CTX = os.environ.get("LLAMA_CTX", "16384")


def connect():
    """도커로 띄운 Postgres에 접속하고 pgvector 타입을 등록한다."""
    try:
        conn = psycopg.connect(DATABASE_URL)
    except psycopg.OperationalError as error:
        raise SystemExit(
            "Postgres에 연결하지 못했습니다. rag 폴더에서 docker compose up -d 를 먼저 실행하세요. "
            f"({error})"
        )
    register_vector(conn)
    return conn


def _healthy():
    try:
        with urllib.request.urlopen(LLAMA_URL + "/health", timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def ensure_server():
    """임베딩 서버가 없으면 LLAMA_BIN과 GGUF로 llama-server를 띄운다."""
    if _healthy():
        return
    binary = os.environ.get("LLAMA_BIN")
    gguf = os.environ.get("GGUF")
    if not binary or not gguf:
        raise SystemExit(
            "임베딩 서버가 없습니다. 6700 XT가 있는 Windows에서 llama-server를 띄우거나, "
            "LLAMA_BIN(llama-server 실행 파일)과 GGUF(Nemotron-3-Embed-8B-Q6_K.gguf 경로)를 지정하세요."
        )
    port = urlparse(LLAMA_URL).port or 8081
    command = [
        binary,
        "-m", gguf,
        "--embeddings",
        "--pooling", "mean",
        "--ctx-size", LLAMA_CTX,
        "-ngl", "99",
        "--parallel", "1",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    print("llama-server를 띄웁니다.", flush=True)
    subprocess.Popen(command)
    deadline = time.time() + 300
    while time.time() < deadline:
        if _healthy():
            return
        time.sleep(2)
    raise SystemExit("llama-server가 5분 안에 준비되지 않았습니다. GGUF 경로와 GPU 메모리를 확인하세요.")


def _normalize(vector):
    """코사인 검색에 맞추려고 벡터 길이를 1로 만든다. 이미 정규화돼 있으면 값이 그대로다."""
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def embed_texts(texts):
    """접두어가 이미 붙은 문자열들을 4096차원 벡터로 받는다."""
    payload = json.dumps({"input": texts, "encoding_format": "float"}).encode()
    request = urllib.request.Request(
        LLAMA_URL + "/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"임베딩 요청이 거절되었습니다. ({error.code}) {detail}")
    except urllib.error.URLError as error:
        raise SystemExit(f"임베딩 서버에 연결하지 못했습니다. {LLAMA_URL} ({error})")
    rows = sorted(body["data"], key=lambda item: item.get("index", 0))
    vectors = [_normalize(item["embedding"]) for item in rows]
    if len(vectors) != len(texts):
        raise SystemExit("임베딩 개수가 입력과 다릅니다.")
    if len(vectors[0]) != DIM:
        raise SystemExit(f"벡터 차원이 {len(vectors[0])}입니다. 이 모델의 {DIM}차원이 아닙니다.")
    return vectors
