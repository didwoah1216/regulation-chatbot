import pymupdf4llm
chunks = pymupdf4llm.to_markdown("../yeonsung_regulations/학칙/2-1-1_학칙.pdf", page_chunks=True)

md = "\n\n".join(f"<!-- page: {i+1} -->\n{c['text']}" for i, c in enumerate(chunks))

open("./md/학칙_pymu.md", "w", encoding="utf-8").write(md)