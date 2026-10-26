"""질문을 임베딩하고, 가까운 조항으로 Gemini 3.5 Flash-Lite가 답하게 한다.

임베딩은 적재와 같은 Q6 GGUF다. 질문 앞에만 query: 를 붙인다.
답변 모델은 GPU에 올리지 않고 API로 호출한다.

  $env:GEMINI_API_KEY="AI Studio에서 받은 키"
  python ask.py 휴학은 얼마나 할 수 있나
"""

import json
import os
import sys
import urllib.error
import urllib.request

from common import QUERY, connect, embed_texts, ensure_server

TOP_K = int(os.environ.get("TOP_K", "5"))
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "gemini-3.5-flash-lite")


def search(conn, vector):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT "규정명", "규정번호", "조", page, content, "연혁",
                   embedding <=> %s AS distance
            FROM regulation_chunk
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (vector, vector, TOP_K),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def format_history(items):
    if not items:
        return "없음"
    parts = []
    for item in items:
        place = f" {item['위치']}" if item.get("위치") else ""
        date = item.get("날짜") or "날짜 없음"
        parts.append(f"{item.get('구분', '')} {date}{place}".strip())
    return ", ".join(parts)


def prompt_for(question, rows):
    blocks = []
    for index, row in enumerate(rows, start=1):
        page = "" if row["page"] is None else f", {row['page']}쪽"
        blocks.append(
            f"[{index}] {row['규정명']} {row['조']}{page}\n"
            f"연혁: {format_history(row['연혁'])}\n"
            f"{row['content']}"
        )
    articles = "\n\n".join(blocks)
    return (
        "너는 연성대학교 규정 챗봇이다. 아래에 검색된 조항만 보고 한국어로 답한다. "
        "조항에 없는 내용은 검색된 규정에서 찾지 못했다고 말한다. "
        "답에는 근거가 된 규정명과 조를 적는다. "
        "연혁은 개정·신설·삭제 시점을 물을 때만 쓴다.\n\n"
        f"질문: {question}\n\n"
        f"조항:\n{articles}"
    )


def generate(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY가 없습니다. Google AI Studio에서 받은 키를 넣으세요.")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{ANSWER_MODEL}:generateContent?key={key}"
    )
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"답변 모델 요청이 거절되었습니다. ({error.code}) {detail}")
    except urllib.error.URLError as error:
        raise SystemExit(f"답변 모델에 연결하지 못했습니다. ({error})")
    candidates = body.get("candidates") or []
    if not candidates:
        raise SystemExit(f"답변 모델이 빈 응답을 보냈습니다. {json.dumps(body, ensure_ascii=False)}")
    texts = []
    for part in candidates[0].get("content", {}).get("parts", []):
        if part.get("thought"):
            continue
        if part.get("text"):
            texts.append(part["text"])
    if not texts:
        raise SystemExit(f"답변 본문이 없습니다. {json.dumps(body, ensure_ascii=False)}")
    return "\n".join(texts).strip()


def main():
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        question = input("질문: ").strip()
    if not question:
        raise SystemExit("질문이 비어 있습니다.")
    ensure_server()
    vector = embed_texts([QUERY + question])[0]
    conn = connect()
    rows = search(conn, vector)
    conn.close()
    if not rows:
        raise SystemExit("저장된 조항이 없습니다. embed.py로 먼저 적재하세요.")
    print("검색", flush=True)
    for row in rows:
        page = "-" if row["page"] is None else str(row["page"])
        print(f"- {row['규정명']} {row['조']} ({page}쪽, 거리 {row['distance']:.4f})", flush=True)
    print("\n답", flush=True)
    print(generate(prompt_for(question, rows)), flush=True)


if __name__ == "__main__":
    main()
