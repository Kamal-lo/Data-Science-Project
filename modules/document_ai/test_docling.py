"""Extract the sample PDF with Docling, PDFium rendering and French OCR.

Test the public-procurement sample with the existing French OCR configuration.
"""

import logging
from pathlib import Path
import unicodedata

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import OcrMode, PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = PROJECT_ROOT / "data" / "samples" / "test_dce.pdf"
OUTPUT_PATH = PROJECT_ROOT / "data" / "outputs" / "docling_dce_result.md"
FRENCH_LETTERS = "àâäçéèêëîïôöùûüÿœÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸŒ"


def main() -> None:
    if not PDF_PATH.is_file():
        raise FileNotFoundError(f"PDF introuvable : {PDF_PATH}")

    # Recognize all rendered pages rather than relying on the PDF text layer.
    # RapidOCR is already installed; explicitly request French recognition.
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=RapidOcrOptions(
            lang=["iso:fr"],
            backend="onnxruntime",
            mode=OcrMode.FULL_PAGE,
            # Keep the configuration verified on the previous sample:
            # orientation classification could wrongly rotate upright lines.
            use_cls=False,
        ),
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                # Keep the PDFium renderer verified on the previous sample.
                backend=PyPdfiumDocumentBackend,
            )
        }
    )

    print("Conversion avec OCR français en cours...", flush=True)
    result = converter.convert(PDF_PATH)
    if result.status != ConversionStatus.SUCCESS:
        raise RuntimeError(f"Conversion incomplète : {result.status}; {result.errors}")

    markdown = unicodedata.normalize("NFC", result.document.export_to_markdown())
    if not markdown.strip():
        raise RuntimeError("Aucun texte extrait ; le fichier de sortie est conservé.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(markdown, encoding="utf-8")

    replacement_count = markdown.count("\uFFFD")
    control_count = sum(
        unicodedata.category(char) == "Cc" and char not in "\n\r\t"
        for char in markdown
    )
    accent_count = sum(char in FRENCH_LETTERS for char in markdown)
    print(f"Fichier : {OUTPUT_PATH}")
    print(f"Pages converties : {len(result.pages)}")
    print(f"Tableaux détectés : {len(result.document.tables)}")
    print(f"Caractères extraits : {len(markdown)}")
    print(f"Caractères de remplacement : {replacement_count}")
    print(f"Caractères de contrôle inattendus : {control_count}")
    print(f"Lettres françaises accentuées : {accent_count}")
    if accent_count == 0:
        print(
            "AVERTISSEMENT : aucun accent français extrait. La qualité du texte "
            "n'est pas validée ; contrôler le rendu et les polices du PDF source."
        )
    print(
        "Vérifier visuellement le Markdown : l'absence de caractères incorrects "
        "ne garantit pas la fidélité de l'OCR. Les lettres absentes de "
        "l'image du PDF ne peuvent pas être restaurées avec certitude."
    )
    if replacement_count or control_count:
        raise RuntimeError("Le Markdown contient encore des caractères incorrects.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
