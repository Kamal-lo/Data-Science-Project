"""T10: run Marker on the same scanned DCE without changing Docling.

API reference: https://github.com/datalab-to/marker
Install nothing automatically. Marker and its OCR backend must be available
before conversion. The first run may download model weights.
"""

from datetime import datetime, timezone
from importlib import metadata, util
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from time import perf_counter
import traceback
import unicodedata


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = PROJECT_ROOT / "data/samples/test_dce.pdf"
OUTPUT_PATH = PROJECT_ROOT / "data/outputs/marker_dce_result.md"
DIAGNOSTICS_DIR = PROJECT_ROOT / "data/outputs/marker_diagnostics"
FRENCH_LETTERS = "àâäçéèêëîïôöùûüÿœÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸŒ"
CONFIG = {
    "force_ocr": True,
    "use_llm": False,
    "paginate_output": True,
    "extract_images": False,
    "html_tables_in_markdown": False,
}


def text_metrics(text: str) -> dict:
    """Count signals, without treating them as an OCR accuracy score."""
    return {
        "characters": len(text),
        "french_accented_letters_and_ligatures": sum(c in FRENCH_LETTERS for c in text),
        "replacement_characters": text.count("\ufffd"),
        "unexpected_controls": sum(
            unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in text
        ),
        "markdown_table_separators": len(re.findall(r"(?m)^\|[\s:|\-]+\|[ \t]*$", text)),
        "french_word_counts": {
            word: text.casefold().count(word)
            for word in ("marché", "exécution", "réception", "sécurité", "végétaux")
        },
    }


def page_texts(markdown: str) -> dict[int, str]:
    """Marker page IDs are zero-based; expose physical PDF pages starting at 1."""
    markers = list(re.finditer(r"(?m)^\{(\d+)\}-{48}[ \t]*$", markdown))
    return {
        int(marker.group(1)) + 1: markdown[
            marker.end(): markers[i + 1].start() if i + 1 < len(markers) else len(markdown)
        ].strip()
        for i, marker in enumerate(markers)
    }


def focus_checks(pages: dict[int, str]) -> dict:
    page25 = pages.get(25, "")
    page27 = pages.get(27, "")
    # These are references read from the original scan, NOT text corrections.
    expected_bpu_values = (
        "260", "8", "208,66", "54 251,60", "1 669,28",
        "55 920,88", "11 184,17", "67 105,05",
    )
    return {
        "page25": {
            "available": 25 in pages,
            "metrics": text_metrics(page25),
            "secateur_found": "sécateur" in page25.casefold(),
            "table_lines_to_review": [line for line in page25.splitlines() if line.startswith("|")],
        },
        "page27": {
            "available": 27 in pages,
            "metrics": text_metrics(page27),
            "reference_values_present": {
                value: bool(re.search(
                    r"(?<!\d)" + r"\s*".join(map(re.escape, value.split())) + r"(?!\d)", page27
                ))
                for value in expected_bpu_values
            },
            "table_lines_to_review": [line for line in page27.splitlines() if line.startswith("|")],
        },
        "note": "Value presence does not validate column assignment; compare pages 25 and 27 visually.",
    }


def main() -> int:
    started = perf_counter()
    try:
        marker_version = metadata.version("marker-pdf")
    except metadata.PackageNotFoundError:
        print("Marker (marker-pdf) n'est pas installé dans cet environnement.", file=sys.stderr)
        print("Aucune installation ni conversion effectuée. Autorisation requise.", file=sys.stderr)
        return 2
    if util.find_spec("marker") is None:
        print("Le paquet marker-pdf est déclaré mais son module marker est absent.", file=sys.stderr)
        return 2
    if not PDF_PATH.is_file():
        print(f"PDF introuvable : {PDF_PATH}", file=sys.stderr)
        return 2
    if OUTPUT_PATH.exists():
        print(f"Sortie existante conservée : {OUTPUT_PATH}", file=sys.stderr)
        return 2

    run_dir = DIAGNOSTICS_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "running", "marker_version": marker_version,
        "python_version": platform.python_version(), "config": CONFIG,
        "source": str(PDF_PATH), "output": str(OUTPUT_PATH),
        "source_sha256": hashlib.sha256(PDF_PATH.read_bytes()).hexdigest(),
        "accuracy_validated": False,
    }
    artifacts = None
    try:
        import pypdfium2
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        with pypdfium2.PdfDocument(PDF_PATH) as pdf:
            report["source_pages"] = len(pdf)
        model_started = perf_counter()
        artifacts = create_model_dict()
        converter = PdfConverter(artifact_dict=artifacts, config=CONFIG.copy())
        report["initialization_seconds"] = perf_counter() - model_started
        report["resolved_marker_mode"] = getattr(converter, "mode", None)

        print(f"Marker {marker_version} : OCR de {report['source_pages']} pages...", flush=True)
        conversion_started = perf_counter()
        rendered = converter(str(PDF_PATH))
        report["conversion_seconds"] = perf_counter() - conversion_started
        markdown = rendered.markdown
        if not markdown.strip():
            raise RuntimeError("Marker n'a extrait aucun texte.")
        # Write the actual Marker output, without spelling/accent substitutions.
        with OUTPUT_PATH.open("x", encoding="utf-8") as output:
            output.write(markdown)
        pages = page_texts(markdown)
        report.update(
            status="converted", metrics=text_metrics(markdown),
            metadata=rendered.metadata, paginated_pdf_pages=sorted(pages),
            all_pages_present=set(pages) == set(range(1, report["source_pages"] + 1)),
            focus_checks=focus_checks(pages),
        )
        for number in (25, 27):
            if number in pages:
                (run_dir / f"page_{number}.md").write_text(pages[number], encoding="utf-8")
        print(f"Fichier : {OUTPUT_PATH}")
        print(f"Pages identifiées : {len(pages)}/{report['source_pages']}")
        print(f"Conversion : {report['conversion_seconds']:.2f} secondes")
        print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
        print("Contrôle visuel des pages 25 et 27 nécessaire avant de valider la qualité.")
        return 0
    except Exception as exc:
        report.update(status="error", error_type=type(exc).__name__, error=str(exc))
        traceback.print_exc()
        return 1
    finally:
        # Marker 2.x exposes a shutdown helper; older versions may not have it.
        if artifacts is not None:
            try:
                from marker import models
                shutdown = getattr(models, "shutdown_models", None)
                if shutdown is not None:
                    shutdown(artifacts)
            except Exception as exc:
                report["cleanup_error"] = str(exc)
        report["total_seconds_including_imports_models_and_cleanup"] = perf_counter() - started
        (run_dir / "verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"Rapport et éventuelles erreurs : {run_dir / 'verification.json'}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
