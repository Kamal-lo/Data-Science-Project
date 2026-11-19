"""CLI depuis la racine du dépôt ; accepte uniquement un manifeste T23."""
import argparse
import json

from . import convert_ingestion, ConversionOptions


def main():
    parser = argparse.ArgumentParser(description='T24 : PDF/DOCX T23 vers Markdown + JSON.')
    parser.add_argument('manifest_path')
    parser.add_argument('--file-id', action='append', dest='file_ids')
    parser.add_argument('--output-dir')
    parser.add_argument('--ocr-mode', choices=('auto', 'never', 'reuse_only'), default='auto')
    parser.add_argument('--ocr-result', action='append', default=[])
    parser.add_argument('--pages', type=int, nargs='+')
    args = parser.parse_args()
    try:
        result = convert_ingestion(args.manifest_path, args.output_dir, file_ids=args.file_ids,
                                  options=ConversionOptions(ocr_mode=args.ocr_mode,
                                                            ocr_results=tuple(args.ocr_result),
                                                            pdf_pages=tuple(args.pages) if args.pages else None))
    except (ValueError, OSError, TypeError) as exc:
        parser.exit(2, 'Entrée refusée : ' + type(exc).__name__ + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in ('completed', 'completed_with_review') else 2


if __name__ == '__main__':
    raise SystemExit(main())
