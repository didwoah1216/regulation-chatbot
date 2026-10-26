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
# <개정 2020.10.01.> 처럼 조문 뒤의 연혁 표시.
# '03.0 1'처럼 일자 앞에 공백이 있거나 '10..'처럼 점이 하나 더 있는 경우도 받는다.
_DATE = r"\d\s*\d\s*\d\s*\d\s*\.\s*\d\s*\d?\s*\.\s*\d\s*\d?\.?"
_DATES = _DATE + r"(?:\s*,\s*" + _DATE + r")*"
_KIND = r"본조\s*신설|전문\s*개정|전부개정|전면개정|일부개정|개정|신설|삭제|제정"
_RANGE = r"제?\d+\s*[항호]\s*부터\s*제?\d+\s*[항호]\s*까지"
_INNER = re.compile(
    r"(?:"
    + r"(?P<range>" + _RANGE + r")\s*(?P<k1>" + _KIND + r")\s*(?P<d1>" + _DATES + r")\.*"
    + r"|(?P<k2>" + _KIND + r")\s*(?P<d2>" + _DATES + r")\.*"
    + r"|(?P<d3>" + _DATES + r")\s*(?P<k3>" + _KIND + r")\.*"
    + r"|(?P<bare>표\s*삭제|본조\s*신설|전문\s*개정|전부개정|전면개정|일부개정|삭제|신설|개정|제정)"
    + r")"
)
# <개정 ② 2022.02.28> 처럼 번호만 끼어 있으면 연혁으로 본다. 본문 문장이 끼면 그대로 둔다.
_LOOSE = re.compile(r"<(?P<k>" + _KIND + r")\s*[^가-힣<>]{0,8}(?P<d>" + _DATE + r")\.*\s*>")
_LOC = re.compile(r"^([①-⑳㉑-㉟]|[0-9]+(?:의[0-9]+)?\.|[가나다라마바사아자차카타파하]\.)")
_DATE_FIND = re.compile(_DATE)


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


def _canon_kind(kind):
    """'전문 개정', '본조 신설'처럼 띄어 쓴 구분을 한 단어로 붙인다."""
    return re.sub(r"\s+", "", kind)


def _canon_date(date):
    """'2021.12. 01.'처럼 날짜 안의 공백만 없앤다. 규정에 적힌 일자는 고치지 않는다."""
    return re.sub(r"\s+", "", date)


def _history_items(matched):
    """괄호 안이 연혁이면 구분·날짜 목록을 만들고, 아니면 None을 돌려준다."""
    if matched is None:
        return None
    if matched.group("bare"):
        bare = _canon_kind(matched.group("bare"))
        if bare == "표삭제":
            return [{"구분": "삭제", "날짜": "", "위치": "표"}]
        return [{"구분": bare, "날짜": "", "위치": ""}]
    if matched.group("range"):
        kind, dates = matched.group("k1"), matched.group("d1")
        place = re.sub(r"\s+", "", matched.group("range"))
    elif matched.group("k2"):
        kind, dates, place = matched.group("k2"), matched.group("d2"), ""
    else:
        kind, dates, place = matched.group("k3"), matched.group("d3"), ""
    kind = _canon_kind(kind)
    return [
        {"구분": kind, "날짜": _canon_date(date), "위치": place}
        for date in _DATE_FIND.findall(dates)
    ]


def _find_history(line):
    """줄에서 가장 앞에 있는 연혁 괄호 하나를 찾는다. 없으면 None."""
    index = 0
    while index < len(line):
        if line[index] not in "<[":
            index += 1
            continue
        close = ">" if line[index] == "<" else "]"
        end = line.find(close, index + 1)
        if end == -1 and line[index] == "<":
            end = line.find(")", index + 1)
        # 날짜를 여러 개 나열한 태그는 길다. 본문 문장이 섞이면 아래 패턴이 거절한다.
        if end != -1 and end - index <= 400:
            items = _history_items(_INNER.fullmatch(line[index + 1:end].strip()))
            if items is not None:
                return index, end + 1, items
        index += 1
    loose = _LOOSE.search(line)
    if loose is not None:
        return loose.start(), loose.end(), [{
            "구분": _canon_kind(loose.group("k")),
            "날짜": _canon_date(loose.group("d")),
            "위치": "",
        }]
    # '>'가 빠진 채 줄 끝의 날짜로 끝나는 표시. '<개정 2019.07.15'
    trail = re.search(r"<(" + _KIND + r")\s*(" + _DATE + r")\s*$", line)
    if trail is None:
        return None
    return trail.start(), trail.end(), [{
        "구분": _canon_kind(trail.group(1)),
        "날짜": _canon_date(trail.group(2)),
        "위치": "",
    }]


def _join_split_tags(lines):
    """'<개정 2016.' 다음 줄이 '9. 1.>'인 경우처럼 줄이 나뉜 태그를 한 줄로 붙인다."""
    opener = re.compile(r"<(?:본조\s*신설|전문\s*개정|전부개정|전면개정|일부개정|개정|신설|삭제|제정)[^>]*$")
    joined = []
    index = 0
    while index < len(lines):
        line = lines[index]
        nxt = lines[index + 1] if index + 1 < len(lines) else ""
        if nxt and opener.search(line) and ">" in nxt and "|" not in line and "|" not in nxt:
            joined.append(line + nxt)
            index += 2
            continue
        joined.append(line)
        index += 1
    return joined


def detach_history(lines):
    """본문에서 연혁 괄호를 빼고, 나온 순서대로 메타데이터 목록을 만든다.

    위치는 그 괄호가 있던 줄의 항·호 번호다. '2항부터 5항까지 삭제'처럼
    괄호 안에 범위가 있으면 그 범위를 위치로 쓴다.
    """
    history = []
    kept = []
    for line in _join_split_tags(lines):
        records = []
        while True:
            found = _find_history(line)
            if found is None:
                break
            start, end, items = found
            records.extend(items)
            line = line[:start] + line[end:]
        line = re.sub(r"[ \t]{2,}", " ", line).strip()
        place = ""
        located = _LOC.match(line)
        if located:
            place = located.group(1)
        for record in records:
            if not record["위치"]:
                record["위치"] = place
            history.append(record)
        if line:
            kept.append(line)
    return "\n".join(kept).strip(), history


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
            body, history = detach_history(lines)
            history = list(current.get("연혁", [])) + history
            if not body and not 조 and not history:
                continue
            head = f"{name} {조}".strip()
            chunks.append({
                "text": head if not body else f"{head}\n{body}",
                "metadata": {
                    "규정명": name,
                    "규정번호": number,
                    "조": 조,
                    "page": current["page"],
                    "연혁": history,
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
                연혁 = current.get("연혁", [])
                close()
                current = {"조": 조, "page": page, "lines": [], "연혁": 연혁}
            continue
        if line.startswith("## "):
            close()
            # 별표·별지 제목에 붙은 <개정>도 조 이름에 남기지 않는다.
            title, heading_history = detach_history([line[3:].strip()])
            current = {"조": title, "page": page, "lines": [], "연혁": heading_history}
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
