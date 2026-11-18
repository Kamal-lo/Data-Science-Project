"""Intégration réelle limitée aux pages 1 et 2 ; aucune zone manuelle."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from P2_nlp_extraction.ocr_pipeline import extract_pdf


def main():
    root = Path(__file__).resolve().parents[1]
    result = extract_pdf(root/'data/pdf/test_dce.pdf', root/'outputs/ocr/automatic_sample',
                         pages=[1, 2], timeout_seconds=600, page_timeout_seconds=240)
    summary = {'status': result['status'], 'run_directory': result['run_directory'],
               'execution_seconds': result['execution_seconds'], 'pages': []}
    for page in result['pages']:
        counts = {lang: sum(b['language'] == lang for b in page['blocks']) for lang in ('fr', 'ar', 'mixed', 'und')}
        summary['pages'].append({'page': page['page'], 'status': page['status'],
                                 'raw_detection_count': page.get('raw_detection_count'),
                                 'block_count': len(page['blocks']), 'languages': counts,
                                 'needs_review': sum(b['needs_review'] for b in page['blocks']),
                                 'timings': page['timings'], 'errors': page['errors']})
    target = Path(result['run_directory'])/'integration_summary.json'
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # Une exécution partielle ne constitue pas une intégration réussie.
    if result['status'] not in ('completed', 'completed_with_review'):
        raise RuntimeError(f"Extraction incomplète : {result['status']}")
    if [p['page'] for p in result['pages']] != [1, 2]:
        raise RuntimeError('Les deux pages attendues ne sont pas présentes.')
    for page in result['pages']:
        if page['errors'] or not page['blocks']:
            raise RuntimeError(f"Page {page['page']} vide ou en erreur.")
        ids = [block['block_id'] for block in page['blocks']]
        if len(ids) != len(set(ids)):
            raise RuntimeError('Identifiants de blocs dupliqués.')
        for block in page['blocks']:
            if set(block['recognition_candidates']) != {'fr', 'ar'}:
                raise RuntimeError('Hypothèses bilingues manquantes.')
    if not any(b['language'] == 'ar' for b in result['pages'][0]['blocks']):
        raise RuntimeError('Aucun en-tête arabe détecté sur la page 1.')
    if not all(any(b['language'] == 'fr' for b in p['blocks']) for p in result['pages']):
        raise RuntimeError('Texte français absent sur une page.')
    for key in ('json', 'raw_txt', 'spacing_txt', 'hypotheses_txt'):
        Path(result['exports'][key]).read_text(encoding='utf-8')
    print('INTEGRATION_OK: pages 1-2, français/arabe, exports UTF-8 et hypothèses vérifiés.')


if __name__ == '__main__':
    main()
