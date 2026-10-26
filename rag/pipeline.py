"""PDF를 마크다운으로 바꾸고, 조항으로 나눈 뒤 Postgres에 임베딩한다.

변환과 청킹은 pdf2md, md2chunk-json의 코드를 그대로 부른다.
6700 XT가 있는 Windows에서 실행한다. Postgres만 도커에 있다.

  docker compose up -d
  $env:LLAMA_BIN="llama-server.exe 경로"
  $env:GGUF="Nemotron-3-Embed-8B-Q6_K.gguf 경로"
  python pipeline.py
"""

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PDF_DIR = os.path.join(ROOT, "yeonsung_regulations")
MD_DIR = os.path.join(ROOT, "pdf2md", "md")
CHUNK_JSON = os.path.join(ROOT, "md2chunk-json", "chunk.json")

sys.path.insert(0, os.path.join(ROOT, "pdf2md"))
sys.path.insert(0, os.path.join(ROOT, "md2chunk-json"))

import chunk as chunker
import test_plumber
import embed


def main():
    if not os.path.isdir(PDF_DIR):
        raise SystemExit(f"PDF 폴더가 없습니다. {PDF_DIR}")
    print("1. PDF를 마크다운으로 바꿉니다.", flush=True)
    failed = test_plumber.convert_tree(PDF_DIR, MD_DIR)
    if failed:
        raise SystemExit(f"마크다운 변환 실패 {len(failed)}개. 임베딩은 시작하지 않습니다.")

    print("2. 조항으로 나눕니다.", flush=True)
    files, chunks = chunker.build(MD_DIR)
    with open(CHUNK_JSON, "w", encoding="utf-8") as target:
        json.dump(chunks, target, ensure_ascii=False, indent=2)
    print(f"파일 {files}개, 청크 {len(chunks)}개 → {CHUNK_JSON}", flush=True)

    print("3. 임베딩해서 Postgres에 넣습니다.", flush=True)
    embed.store(chunks)


if __name__ == "__main__":
    main()
