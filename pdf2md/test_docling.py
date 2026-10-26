from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions

SRC = "../yeonsung_regulations/학칙/2-1-1_학칙.pdf"
DST = "./md/학칙_docling.md"

# 글자가 들어 있는 PDF라 OCR(그림에서 글자 읽기)은 끄고, 표 구조 인식만 켬
opt = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
conv = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opt)}
)

doc = conv.convert(SRC).document

# 쪽마다 따로 꺼내서 앞에 쪽 표시 붙이기
parts = []
for p in sorted(doc.pages):
    parts.append(f"<!-- page: {p} -->\n" + doc.export_to_markdown(page_no=p))
md = "\n\n".join(parts)

open(DST, "w", encoding="utf-8").write(md)
print("완료:", DST)