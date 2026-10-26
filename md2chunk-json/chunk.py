import json
import os
import re

# 변환된 마크다운. test_plumber.py가 만든 md 폴더를 그대로 읽는다.
MD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../pdf2md/md")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chunk.json")

PAGE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
TABLE_SPLIT = "<!-- table-split -->"
# '2. 전기안전 연구실에서…'처럼 번호와 제목 뒤에 본문이 같은 줄에 붙는다.
SECTION_LINE = re.compile(r"^(\d+)\.\s+(\S+)(?:\s+(.*))?$")
# 연구실 안전관리규정 [별표10]. 마크다운에서는 제목이 하나라 3만 자가 한 조각이 된다.
SAFETY_APPENDIX = "[별표10]"


def regulation_from_name(filename):
    """'3-5-1_장학규정.md'에서 규정번호와 규정명을 꺼낸다."""
    stem = os.path.splitext(filename)[0]
    number, _, name = stem.partition("_")
    if not name:
        return "", stem
    return number, name


def section_parts(line):
    """번호로 시작하는 안전수칙 제목을 본문과 가른다.

    '1. 일반안전'은 줄 전체가 제목이다.
    '2. 전기안전 연구실에서…'는 제목이 '2. 전기안전'이고 나머지가 본문이다.
    """
    matched = SECTION_LINE.match(line)
    if not matched:
        return None
    number, first, rest = matched.group(1), matched.group(2), (matched.group(3) or "").strip()
    if not rest or len(line) <= 40:
        return line.strip(), ""
    return f"{number}. {first}", rest


def split_safety_sections(조, lines):
    """[별표10] 유형별 안전수칙을 '1. 일반안전' 같은 줄마다 나눈다."""
    groups = []
    title = None
    buf = []

    def flush():
        if title is None and not any(buf):
            return
        groups.append((title, [line for line in buf if line]))

    for line in lines:
        parts = section_parts(line)
        if parts:
            flush()
            title, rest = parts
            buf = [rest] if rest else []
            continue
        buf.append(line)
    flush()
    if len(groups) < 2:
        return [(조, lines)]
    return [(f"{조} {title}".strip() if title else 조, buf) for title, buf in groups]


def split_markdown(text, name, number):
    """한 규정 마크다운을 조항 단위 조각으로 나눈다.

    ## 제N조, ## 부칙, ## [별표], ## [별지]에서 새 조각을 연다.
    긴 표는 <!-- table-split -->마다 같은 조 이름으로 한 번 더 나눈다.
    # 제N장과 파일 제목은 조가 아니라서 어느 조각에도 넣지 않는다.
    """
    page = None
    current = None
    chunks = []

    def close():
        """지금 모으던 조각을 저장하고 비운다. 본문이 없는 머리말은 버린다."""
        nonlocal current
        if current is None:
            return
        pieces = [(current["조"], current["lines"])]
        if current["조"].startswith(SAFETY_APPENDIX):
            pieces = split_safety_sections(current["조"], current["lines"])
        for 조, lines in pieces:
            body = "\n".join(lines).strip()
            if not body and not 조:
                continue
            head = f"{name} {조}".strip()
            chunks.append({
                "text": head if not body else f"{head}\n{body}",
                "metadata": {
                    "규정명": name,
                    "규정번호": number,
                    "조": 조,
                    "page": current["page"],
                },
            })
        current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # 쪽수 표시는 본문에 남기지 않고, 다음에 여는 조각의 page로만 쓴다.
        marker = PAGE.fullmatch(line)
        if marker:
            page = int(marker.group(1))
            continue
        # 표가 15줄을 넘으면 같은 조를 유지한 채 다음 조각으로 넘긴다.
        if line == TABLE_SPLIT:
            if current and current["lines"]:
                조 = current["조"]
                close()
                current = {"조": 조, "page": page, "lines": []}
            continue
        if line.startswith("## "):
            close()
            current = {"조": line[3:].strip(), "page": page, "lines": []}
            continue
        # '# 제1장', '# 3-5-1_장학규정'은 조 제목이 아니다.
        if line.startswith("# "):
            continue
        # 첫 조 앞의 제정일처럼 조 번호가 없는 줄은 머리말로 모은다.
        if current is None:
            current = {"조": "", "page": page, "lines": []}
        current["lines"].append(line)

    close()
    return chunks


def build(md_dir):
    """md 폴더의 규정 파일을 전부 읽어 조각 목록으로 만든다."""
    chunks = []
    files = 0
    for root, _, names in os.walk(md_dir):
        for name in sorted(names):
            if not name.lower().endswith(".md"):
                continue
            number, title = regulation_from_name(name)
            path = os.path.join(root, name)
            text = open(path, encoding="utf-8").read()
            chunks.extend(split_markdown(text, title, number))
            files += 1
    return files, chunks


if __name__ == "__main__":
    files, chunks = build(MD_DIR)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"파일 {files}개, 청크 {len(chunks)}개 → {OUT}", flush=True)
