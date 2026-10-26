import os, re
import pdfplumber

SRC = "../yeonsung_regulations"  # PDF 원본 폴더. 하위 폴더 구조를 그대로 md에 만든다.
DST = "md"                        # MD 파일 저장 폴더
TOP, BOTTOM = 100, 70             # 머리말/쪽번호 영역 높이(pt)
_kiwi = None


def get_kiwi():
    """줄바꿈으로 갈라진 단어만 판단하는 한국어 분석기. 처음 호출할 때 모델을 읽는다."""
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    return _kiwi


def boundary_needs_space(prev, nxt):
    """앞줄 마지막 단어와 다음 줄 첫 단어 사이에 띄어쓰기가 필요한지.

    예: '소통교'+'육을'은 한 단어라 붙이고, '인성'+'교육'은 띄어 쓴다.
    판단은 그 경계만 보고, 줄 안에 원래 있던 띄어쓰기는 바꾸지 않는다.
    """
    last = re.search(r"[가-힣]+$", prev)
    first = re.match(r"[가-힣]+", nxt)
    if not last or not first:
        # "2017.03.0 | 1."처럼 숫자만 잘린 줄은 띄어쓰지 않는다.
        if re.search(r"\d$", prev) and re.match(r"\d", nxt):
            return False
        return True
    last_h, first_h = last.group(), first.group()
    # "거쳐야 | 한다", "하고자 | 할"은 띄어 쓴다. 분석기가 한 단어로 붙이는 경우다.
    if last_h.endswith(("야", "어", "아", "게", "지", "고", "여")) and first_h.startswith(("한다", "하며", "하고", "하면", "하여", "할")):
        return True
    spaced = get_kiwi().space(last_h + first_h)
    count = 0
    for ch in spaced:
        if ch == " ":
            if count == len(last_h):
                return True
            continue
        count += 1
    return False


def fill_merged(t):
    """병합 셀(None)을 원래 칸의 값으로 채우기
    - 위아래로 합쳐진 칸: 위 칸 값을 복사 (예: 계열, 통합되는 학과)
    - 좌우로 합쳐진 칸: 머리줄이면 복사, 본문이면 빈칸
    반환값: (표 데이터, 머리줄 줄 수)"""
    rows = t.extract()
    xs = sorted({round(c[0], 1) for c in t.cells})          # 칸 왼쪽 경계
    ys = sorted({round(c[1], 1) for c in t.cells})          # 줄 위쪽 경계
    origin = {}                                             # (줄, 칸) -> 셀 위치
    for c in t.cells:
        origin[(ys.index(round(c[1], 1)), xs.index(round(c[0], 1)))] = c
    # 첫 줄의 셀이 둘째 줄까지 내려오면 머리줄이 2줄인 표
    head_n = 1
    for (r, k), c in origin.items():
        if r == 0 and len(rows) > 1 and c[3] > ys[1] + 1 and k > 0:
            head_n = 2
    for r, row in enumerate(rows):
        for k, v in enumerate(row):
            if v is not None or r >= len(ys) or k >= len(xs):
                continue
            for (r0, k0), c in origin.items():
                if c[0] - 1 <= xs[k] < c[2] - 1 and c[1] - 1 <= ys[r] < c[3] - 1:
                    src = rows[r0][k0] or ""
                    vertical = r0 < r and k0 == k
                    row[k] = src if (vertical or r < head_n) else ""
                    break
    return rows, head_n


MAX_ROWS = 15  # 표 한 조각의 최대 줄 수
WRAP = "\u2060"  # 오른쪽 끝까지 찬 줄 표시. 출력 전에는 지운다.
# 가. 나. 다. … 하. 목록. [가-하]로 쓰면 그 사이 음절이 모두 포함된다.
LIST_MARK = "가나다라마바사아자차카타파하"


def table_to_md(rows, head_n=1):
    """표(2차원 리스트)를 마크다운 표로 바꾸기. 머리줄이 2줄이면 '위 - 아래'로 합침"""
    rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in rows]
    if head_n == 2 and len(rows) > 2:
        top, sub = rows[0], rows[1]
        head = [a if (not b or a == b) else f"{a} - {b}" for a, b in zip(top, sub)]
        rows = [head] + rows[2:]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        return ""
    head, body = rows[0], rows[1:]
    # 머리줄 이름이 겹치면(학과 | 학과) 뒤에 번호 붙이기 → 학과 | 학과2
    seen = {}
    for i, h in enumerate(head):
        if h in seen:
            seen[h] += 1
            head[i] = f"{h}{seen[h]}"
        else:
            seen[h] = 1
    hdr = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    # 긴 표는 MAX_ROWS줄씩 나누고, 조각마다 머리줄을 다시 붙이기
    parts = []
    for i in range(0, len(body), MAX_ROWS):
        chunk = body[i:i + MAX_ROWS]
        parts.append("\n".join(hdr + ["| " + " | ".join(r) + " |" for r in chunk]))
    return "\n<!-- table-split -->\n".join(parts)

def form_image_note(body, page_no, text):
    """서식 그림만 자리표시로 남긴다. OCR은 쓰지 않는다.

    페이지의 40% 이상을 그림이 차지하고 글자가 거의 없으면 서식이다.
    학칙 43~47쪽은 글자가 없고, 학점은행제 학위증서는 제목 한 줄만 있다.
    로고, 직인, 안전표지처럼 본문과 같이 있는 그림은 비율이 작아서 여기서 빠진다.
    """
    imgs = body.images or []
    if not imgs or not body.width or not body.height:
        return text
    area = sum(max(0, im["x1"] - im["x0"]) * max(0, im["bottom"] - im["top"]) for im in imgs)
    cover = area / (body.width * body.height)
    stripped = text.strip()
    if cover < 0.4 or len(stripped) >= 80:
        return text
    note = f"[이미지: 서식 – 원문 PDF {page_no}쪽 참조]"
    return note if not stripped else stripped + "\n" + note


def page_to_md(page, page_no):
    """한 페이지: 머리말/쪽번호 잘라내고, 본문과 표를 위에서부터 순서대로 합치기"""
    body = page.crop((0, TOP, page.width, page.height - BOTTOM))
    tables = body.find_tables()

    def outside(obj):
        return not any(t.bbox[0] <= obj["x0"] <= t.bbox[2] and
                       t.bbox[1] <= obj["top"] <= t.bbox[3] for t in tables)

    blocks = []  # (세로 위치, 내용)
    text_only = body.filter(lambda o: "x0" not in o or outside(o))
    lines = text_only.extract_text_lines()
    # 양쪽 맞춤이라 문장이 이어진 줄은 오른쪽 끝이 같다
    right = max((ln["x1"] for ln in lines), default=0)
    for line in lines:
        text = line["text"]
        # 끝에서 24pt 안쪽이면 다음 글자가 줄바꿈으로 넘어간 줄이다.
        if right and line["x1"] >= right - 24:
            text += WRAP
        blocks.append((line["top"], text))
    for t in tables:
        md = table_to_md(*fill_merged(t))
        if md:
            blocks.append((t.bbox[1], "\n" + md + "\n"))
    blocks.sort(key=lambda b: b[0])
    text = "\n".join(b[1] for b in blocks)
    return form_image_note(body, page_no, text)


def clean(text):
    """남은 머리말/쪽번호 지우기, 끊긴 줄 이어 붙이기, 조문에 제목 표시
    <!-- page: N --> 줄은 그대로 남겨서 나중에 조각마다 쪽수를 붙일 때 씀"""
    # 글꼴이 따옴표를 U+0000으로 적는다. 한 글자는 따옴표로 되돌리고, 서식 밑줄처럼 이어진 것은 지운다.
    text = re.sub(r"\x00{2,}", "", text)
    text = text.replace("\x00", '"')
    text = re.sub(r"^.*●●●.*$", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+-\d+-\d+~\d+\s*$", "", text, flags=re.M)

    appendix = re.compile(r"^[\[<【]\s*별\s*(표|지)\s*(제\s*)?(\d+)?\s*(호)?\s*(의\s*\d+)?\s*(서식)?\s*[\]>】]\s*(.*)$")
    # [이미지: …] 는 빈 페이지 자리표시. 앞 문장에 이어 붙이면 안 된다.
    starts = re.compile(rf"^(<!-- page|\[이미지:|[\[<【]\s*별\s*(표|지)|제\s*\d+\s*(장|절|조)|부\s*칙|\[별표|별지|[①-⑳➀-➉]|\d{{1,2}}(의\d+)?\.(\s|$)|[{LIST_MARK}]\.\s+[가-힣]|\|)")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 오른쪽 끝까지 찬 줄만 단어가 잘렸을 수 있다
        wrapped = line.endswith(WRAP)
        line = line.replace(WRAP, "").strip()
        if not line:
            continue
        prev = len(out) - 1
        while prev >= 0 and out[prev].startswith("<!--"):
            prev -= 1
        prev_text = out[prev][:-len(WRAP)] if prev >= 0 and out[prev].endswith(WRAP) else (out[prev] if prev >= 0 else "")
        prev_wrapped = prev >= 0 and out[prev].endswith(WRAP)
        joinable = prev >= 0 and not prev_text.startswith("|")
        # "설정하고, 제3조에 따라"처럼 쉼표 뒤에서 조 번호가 이어지면 새 조문이 아니다
        mid = joinable and re.match(r"^제\s*\d+\s*조", line) and prev_text.endswith(",")
        # "정한 | 다. <개정>"은 목록이 아니라 "정한다."가 잘린 것이다.
        fake_end = prev_wrapped and re.match(r"^다\.(?:\s*<|\s*단[,，]|\s*$)", line)
        if joinable and (mid or fake_end or not starts.match(line)):
            # 잘린 단어(소통교+육, 재적하+는)만 붙이고, 인성+교육처럼 단어 사이는 띄운다
            glue = prev_wrapped and not boundary_needs_space(prev_text, line)
            out[prev] = prev_text + ("" if glue else " ") + line
            if wrapped:
                out[prev] += WRAP
        else:
            out.append(line + (WRAP if wrapped else ""))

    # "나. 신문방송국 다. 삭제"처럼 한 줄에 붙은 항목을 줄마다 나눈다
    lines = []
    for line in out:
        line = line.replace(WRAP, "")
        if line.startswith("|") or line.startswith("<!--"):
            lines.append(line)
        else:
            lines.extend(re.split(rf"(?<=\S)\s+(?=[{LIST_MARK}]\.\s+[가-힣])", line))

    md = []
    for line in lines:
        if re.match(r"^제\s*\d+\s*장", line):
            md.append("\n# " + line)
        elif re.match(r"^제\s*\d+\s*조(의\s*\d+)?\s*\(", line):
            m = re.match(r"^(제\s*\d+\s*조(의\s*\d+)?\s*\([^)]*\))\s*(.*)$", line)
            md.append("\n## " + m.group(1))
            if m.group(3):
                md.append(m.group(3))
        elif re.match(r"^부\s*칙", line):
            md.append("\n## 부칙")
            rest = re.sub(r"^부\s*칙\s*", "", line)
            if rest:                      # "부칙 ① (시행일) …"처럼 붙은 내용은 살림
                md.append(rest)
        elif appendix.match(line):
            m = appendix.match(line)
            kind = "별표" if m.group(1) == "표" else "별지"
            num = (m.group(3) or "") + (re.sub(r"\s", "", m.group(5)) if m.group(5) else "")
            title = f"[{kind}{num}]" if kind == "별표" else f"[별지 제{num}호 서식]"
            rest = m.group(7)
            tag = re.match(r"^(<(개정|신설|삭제)[^>]*>)\s*(.*)$", rest)
            if tag:
                rest = (tag.group(3) + " " + tag.group(1)).strip()
            md.append(("\n## " + title + " " + rest).rstrip())
        else:
            md.append(line)
    return "\n".join(md).strip() + "\n"


def convert(pdf_path, md_path):
    with pdfplumber.open(pdf_path) as pdf:
        raw = "\n".join(f"<!-- page: {i} -->\n" + page_to_md(p, i)
                        for i, p in enumerate(pdf.pages, start=1))
    title = os.path.splitext(os.path.basename(pdf_path))[0]
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n" + clean(raw))


def convert_tree(src_root, dst_root):
    """PDF 폴더 구조를 유지한 채 같은 상대 경로의 마크다운으로 바꾼다.

    예: 행정/학생행정/3-5-1_장학규정.pdf → md/행정/학생행정/3-5-1_장학규정.md
    """
    ok, failed = 0, []
    for root, _, files in os.walk(src_root):
        for name in sorted(files):
            if not name.lower().endswith(".pdf"):
                continue
            pdf_path = os.path.join(root, name)
            rel = os.path.relpath(pdf_path, src_root)
            md_path = os.path.join(dst_root, os.path.splitext(rel)[0] + ".md")
            try:
                convert(pdf_path, md_path)
                ok += 1
                print(f"완료 {ok}: {rel}", flush=True)
            except Exception as e:
                failed.append((rel, str(e)))
                print(f"실패: {rel} ({e})", flush=True)
    print(f"변환 {ok}개, 실패 {len(failed)}개", flush=True)
    return failed


if __name__ == "__main__":
    convert_tree(SRC, DST)