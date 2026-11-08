"""Historical OCR audit of the unavailable 12-page data/samples/test.pdf.

Archived from modules/document_ai/tests/diagnose_ocr.py; not a T10 DCE test.
Requires the exact original PDF, the historical dependencies and Windows Arial.
PDF object numbers below are specific to that original document.
If the source is restored, evidence is written under data/outputs/ocr_diagnostics.
The missing-source check must run before creating any output.
No text substitutions or linguistic repair are applied to OCR results.
"""

import argparse
import gc
import hashlib
import json
import logging
from pathlib import Path
import threading
import unicodedata
import zlib

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import OcrMode, PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "data/outputs/ocr_diagnostics"
PDF = ROOT / "data/samples/test.pdf"
FRENCH = "àâäçéèêëîïôöùûüÿœÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸŒ"


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def metrics(text):
    return {
        "characters": len(text),
        "replacement_characters": text.count("\ufffd"),
        "accented_letters": sum(c in FRENCH for c in text),
        "unexpected_controls": sum(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in text),
    }


def source_evidence():
    doc = pymupdf.open(PDF)
    result = {"sha256": hashlib.sha256(PDF.read_bytes()).hexdigest(), "pages": len(doc), "streams": []}
    for page_no in (0, 1):
        doc[page_no].get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(OUT / f"original_mupdf_page{page_no + 1}.png")
    for xref in (16, 17, 20, 21, 24, 25):
        raw = doc.xref_stream_raw(xref)
        item = {"xref": xref, "dictionary": doc.xref_object(xref), "raw_prefix_hex": raw[:24].hex(),
                "utf8_replacement_sequences": raw.count(b"\xef\xbf\xbd")}
        try:
            zlib.decompress(raw)
            item["zlib_valid"] = True
        except zlib.error as exc:
            item.update(zlib_valid=False, error=str(exc))
        result["streams"].append(item)
    result["native_text_metrics"] = metrics("".join(page.get_text() for page in doc))
    write_json("source_pdf.json", result)


def synthetic_image():
    lines = ["Répartition de l'équipe et plan de tâches", "Plateforme IA de réponse aux marchés publics marocains",
             "Mémoire technique : fiabilité, conformité, pièces et dépôt."]
    image = Image.new("RGB", (1750, 260), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 48)
    for i, line in enumerate(lines):
        draw.text((25, 15 + 80 * i), line, font=font, fill="black")
    image.save(OUT / "french_control.png")
    return image, lines


def audit(name, scale, last_page, detailed=False):
    pages = []
    context = threading.local()
    original_call = RapidOcrModel.__call__
    original_read = RapidOcrModel._read
    original_rects = RapidOcrModel.get_ocr_rects

    def traced_rects(self, page):
        rects = original_rects(self, page)
        context.record["rectangles"] = [r.model_dump(mode="json") for r in rects]
        context.record["page_size"] = page.size.model_dump(mode="json")
        return rects

    def traced_read(self, image):
        record = context.record
        record.setdefault("input_image_sizes", []).append(list(image.size))
        if record["page"] <= 2:
            image.save(OUT / f"{name}_ocr_input_page{record['page']}.png")
        lines = original_read(self, image)
        record["raw_ocr_lines"] = [{"text": text, "confidence": float(score)} for _, text, score in (lines or [])]
        return lines

    def traced_call(self, conv_res, page_batch):
        for page in page_batch:
            record = {"page": page.page_no, "mode": self.options.mode.value, "scale": self.scale}
            context.record = record
            for processed in original_call(self, conv_res, [page]):
                record["ocr_cells"] = sum(cell.from_ocr for cell in processed.cells)
                record["native_cells"] = sum(not cell.from_ocr for cell in processed.cells)
                pages.append(record)
                print(f"{name}: page {page.page_no}, OCR={record['ocr_cells']}, native={record['native_cells']}", flush=True)
                yield processed

    RapidOcrModel.__call__ = traced_call
    RapidOcrModel._read = traced_read
    RapidOcrModel.get_ocr_rects = traced_rects
    try:
        options = PdfPipelineOptions(do_ocr=True, ocr_options=RapidOcrOptions(
            lang=["iso:fr"], backend="onnxruntime", mode=OcrMode.FULL_PAGE, scale=scale,
            use_cls=False if detailed else None,
            rapidocr_params={"Global.max_side_len": 4000, "Det.limit_side_len": 1280} if detailed else {},
        ))
        converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(
            pipeline_options=options, backend=PyPdfiumDocumentBackend,
        )})
        result = converter.convert(PDF, page_range=(1, last_page))
        markdown = result.document.export_to_markdown()
        (OUT / f"{name}.md").write_text(markdown, encoding="utf-8")
        pipeline = next(iter(converter.initialized_pipelines.values()))
        model = pipeline.ocr_model
        reader = model.reader
        rec = reader.text_rec
        charset = rec.postprocess_op.character
        session = rec.session.session
        model_path = Path(session._model_path)
        control_image, expected = synthetic_image()
        control = original_read(model, control_image) or []
        control_text = "\n".join(line[1] for line in control)
        (OUT / f"{name}_french_control.txt").write_text(control_text, encoding="utf-8")
        tables = [{"page": t.prov[0].page_no if t.prov else None, "rows": t.data.num_rows,
                   "columns": t.data.num_cols, "markdown": t.export_to_markdown(doc=result.document)}
                  for t in result.document.tables]
        evidence = {"status": str(result.status), "configuration": options.ocr_options.model_dump(mode="json"),
                    "pages": sorted(pages, key=lambda p: p["page"]), "metrics": metrics(markdown), "tables": tables,
                    "model": {"class": type(model).__name__, "resolved_codes": model._native_codes,
                              "recognition_config": str(reader.cfg.Rec), "path": str(model_path),
                              "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
                              "charset_size": len(charset), "charset_french": {c: c in charset for c in "éèàçêôùîœ"}},
                    "control": {"expected": expected, "actual": control_text, "metrics": metrics(control_text),
                                "all_lines_exact": control_text == "\n".join(expected)}}
        write_json(f"{name}.json", evidence)
        print(json.dumps({"name": name, "metrics": evidence["metrics"], "control": evidence["control"]}, ensure_ascii=False), flush=True)
    finally:
        RapidOcrModel.__call__ = original_call
        RapidOcrModel._read = original_read
        RapidOcrModel.get_ocr_rects = original_rects


def classification_check():
    """Isolate orientation classification on the exact same page image."""
    model = RapidOcrModel(enabled=True, artifacts_path=None,
                          options=RapidOcrOptions(lang=["iso:fr"], mode=OcrMode.FULL_PAGE),
                          accelerator_options=AcceleratorOptions())
    image = Image.open(OUT / "baseline_216dpi_ocr_input_page2.png").convert("RGB")
    evidence = {}
    for label, use_cls in (("default", None), ("disabled", False)):
        model.options.use_cls = use_cls
        lines = model._read(image) or []
        evidence[label] = [{"text": text, "confidence": float(score)} for _, text, score in lines]
        print(label, json.dumps(evidence[label], ensure_ascii=False), flush=True)
    write_json("orientation_comparison.json", evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["all", "baseline", "300dpi", "300dpi-detail", "classification-check"], default="all")
    args = parser.parse_args()
    if not PDF.is_file():
        parser.error(
            f"Diagnostic historique indisponible : PDF source introuvable : {PDF}. "
            "Restaurer l'ancien fichier test.pdf pour reproduire ces essais. "
            "Aucune sortie de diagnostic n'a ete creee."
        )
    OUT.mkdir(parents=True, exist_ok=True)
    source_evidence()
    if args.variant in ("all", "baseline"):
        audit("baseline_216dpi", 3.0, 12)
        gc.collect()
    if args.variant in ("all", "300dpi"):
        audit("alternative_300dpi", 300 / 72, 2)
        gc.collect()
    if args.variant in ("all", "300dpi-detail"):
        audit("alternative_300dpi_detail", 300 / 72, 2, detailed=True)
    if args.variant in ("all", "classification-check"):
        classification_check()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
