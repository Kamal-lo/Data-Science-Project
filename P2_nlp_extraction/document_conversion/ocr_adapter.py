"""Adaptateur de l'API OCR publique existante ; pas de second moteur OCR."""
import math

from .manifest_validation import confined, load_json, relative
from .models import ConversionFailure, new_block


def adapt_page(record, geometry, limits, provenance):
    number = record.get('page')
    if type(number) is not int or number != geometry['page']:
        raise ConversionFailure('ocr_page_mismatch', 'Indice de page OCR incohérent.')
    if not isinstance(record.get('blocks'), list) or len(record['blocks']) > limits.max_blocks_per_page:
        raise ConversionFailure('ocr_block_limit', 'Blocs OCR absents ou trop nombreux.')
    blocks, chars = [], 0
    for source in record['blocks']:
        if not isinstance(source, dict) or not isinstance(source.get('recognition_candidates', {}), dict) or not isinstance(source.get('warnings', []), list) or any(not isinstance(w, str) for w in source.get('warnings', [])):
            raise ConversionFailure('ocr_block_invalid', 'Structure de bloc OCR invalide.')
        raw = source.get('raw_text')
        if raw is not None and not isinstance(raw, str):
            raise ConversionFailure('ocr_text_invalid', 'Texte OCR invalide.')
        chars += len(raw or '')
        if chars > limits.max_characters_per_page:
            raise ConversionFailure('character_limit', 'Trop de caractères OCR.')
        bbox = source.get('bbox_pdf_points')
        if not isinstance(bbox, list) or len(bbox) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in bbox):
            raise ConversionFailure('ocr_coordinates_invalid', 'Coordonnées OCR en points PDF absentes ou invalides.')
        if not (0 <= bbox[0] < bbox[2] <= geometry['width'] + 1 and 0 <= bbox[1] < bbox[3] <= geometry['height'] + 1):
            raise ConversionFailure('ocr_coordinates_invalid', 'Coordonnées OCR hors de la page.')
        b = new_block('paragraph' if raw is not None else 'unresolved', raw, 'ocr',
                      page=number, bbox=bbox,
                      source_reference={**provenance, 'ocr_block_id': source.get('block_id')},
                      recognition_candidates=source.get('recognition_candidates', {}),
                      arabic_spacing_proposal=source.get('arabic_spacing_proposal'),
                      selected_candidate=source.get('selected_candidate'),
                      routing_reason=source.get('routing_reason'),
                      original_reading_order=source.get('reading_order'),
                      ocr_geometry={k: source[k] for k in ('polygon', 'bbox', 'bbox_pdf_points') if k in source},
                      language_basis=source.get('language_basis'))
        b['language'] = source.get('language') if source.get('language') in ('fr', 'ar', 'und', 'mixed') else 'und'
        b['direction'] = 'rtl' if b['language'] == 'ar' else source.get('direction', 'ltr')
        b['needs_review'] = True  # Le routage bilingue n'est pas une validation humaine.
        b['warnings'] = list(source.get('warnings', [])) + ['ocr_unvalidated_experimental_bilingual_routing']
        recovery_fields = ('primary_raw_text', 'recognition_attempts', 'selected_attempt', 'fallback_used',
                           'fallback_attempted', 'fallback_skipped_reason', 'quality')
        if any(k in source for k in recovery_fields):
            b['ocr_recovery'] = {k: source[k] for k in recovery_fields if k in source}
        if raw is None:
            b['warnings'].append('recognition_unresolved_see_candidates')
        if b['arabic_spacing_proposal'] is not None:
            if not isinstance(b['arabic_spacing_proposal'], dict):
                raise ConversionFailure('ocr_spacing_invalid', 'Proposition d’espacement OCR invalide.')
            b['arabic_spacing_proposal'] = {**b['arabic_spacing_proposal'], 'human_validated': False}
        blocks.append(b)
    return blocks


def cached_pages(paths, digest, geometries, options, limits):
    found = {}
    for source in paths:
        path = confined(source)
        data, checksum = load_json(path, limits.max_output_bytes)
        if (not isinstance(data, dict) or data.get('schema_version') != 'p2.automatic_ocr.v1'
                or data.get('pdf_sha256') != digest):
            raise ConversionFailure('ocr_source_mismatch', 'JSON OCR incompatible avec le SHA-256 de la source.')
        if not isinstance(data.get('pages'), list):
            raise ConversionFailure('ocr_result_invalid', 'Pages OCR absentes.')
        selected = data.get('selected_pages')
        if not isinstance(selected, list) or any(type(n) is not int or n < 1 for n in selected) or len(set(selected)) != len(selected):
            raise ConversionFailure('ocr_selection_invalid', 'Sélection de pages OCR invalide.')
        for page in data['pages']:
            if not isinstance(page, dict):
                raise ConversionFailure('ocr_result_invalid', 'Enregistrement de page OCR invalide.')
            number = page.get('page')
            if type(number) is not int or number not in geometries:
                continue
            if number in found:
                raise ConversionFailure('ocr_duplicate_page', 'Plusieurs résultats OCR pour la même page ; choix humain nécessaire.')
            if number not in selected:
                raise ConversionFailure('ocr_selection_invalid', 'Page absente de la sélection déclarée par le résultat OCR.')
            if not isinstance(page.get('warnings', []), list) or not isinstance(page.get('errors', []), list) or any(not isinstance(e, dict) for e in page.get('errors', [])):
                raise ConversionFailure('ocr_result_invalid', 'Erreurs/avertissements OCR invalides.')
            status = page.get('status')
            if status not in ('ok', 'needs_review', 'near_blank', 'no_text_detected', 'error', 'processing'):
                raise ConversionFailure('ocr_status_invalid', 'Statut OCR inconnu.')
            if status not in ('error', 'processing') and page.get('dpi') != options.ocr_dpi:
                raise ConversionFailure('ocr_dpi_mismatch', 'Résolution du résultat OCR incompatible.')
            provenance = {'ocr_json': relative(path), 'ocr_json_sha256': checksum,
                          'ocr_run_id': data.get('run_id'), 'ocr_status': page.get('status')}
            for key in ('detection_attempts', 'fallback', 'quality_summary', 'fallback_interruption', 'memory_events'):
                if key in page:
                    provenance[key] = page[key]
            # These are diagnostics only, never paths to follow or proof of OCR accuracy.
            provenance['ocr_runtime'] = {key: data[key] for key in
                ('status', 'attempts', 'errors', 'resource_policy') if key in data}
            if isinstance(page.get('preprocessing'), dict):
                # Les chemins image déclarés dans le JSON OCR ne sont ni suivis
                # ni recopiés comme chemins absolus dans le document portable.
                provenance['preprocessing'] = {k: page['preprocessing'][k] for k in
                    ('primary_variant', 'selected_variant', 'parameters', 'geometry_changed', 'coordinate_transform')
                    if k in page['preprocessing']}
            metadata = data.get('model_metadata')
            if isinstance(metadata, dict):
                provenance['model_metadata'] = {k: metadata[k] for k in
                    ('versions', 'models', 'parameters', 'downloads', 'model_load_counts', 'model_load_events')
                    if k in metadata}
            blocks = adapt_page(page, geometries[number], limits, provenance)
            found[number] = {'blocks': blocks, 'status': page.get('status'),
                             'warnings': page.get('warnings', []), 'errors': page.get('errors', []),
                             'timings': page.get('timings', {}), 'provenance': provenance}
    return found


def recognize(pdf_path, numbers, folder, options, limits, budget, *, backend=None):
    """Un appel par petit lot de pages. backend est injectable en tests seulement."""
    if options.ocr_mode != 'auto':
        return None
    if len(numbers) > limits.max_ocr_pages:
        raise ConversionFailure('ocr_page_limit', 'Trop de pages OCR demandées.')
    budget.tick()
    if backend is None:
        from ..ocr_pipeline import extract_pdf
        backend = extract_pdf
    try:
        return backend(pdf_path, output_dir=folder, pages=numbers, dpi=options.ocr_dpi,
                       arabic_spacing='suggest', on_error='continue', cpu_threads=2,
                       fallback_mode=options.ocr_fallback_mode,
                       max_fallback_blocks=options.ocr_max_fallback_blocks,
                       fallback_timeout_seconds=min(options.ocr_fallback_timeout_seconds, max(.1, budget.remaining)),
                       timeout_seconds=max(.1, budget.remaining),
                       page_timeout_seconds=max(.1, min(240, budget.remaining)),
                       initialization_timeout_seconds=max(.1, min(120, budget.remaining)),
                       max_pixels=limits.max_pixels,
                       max_worker_memory_bytes=limits.max_worker_memory_bytes,
                       **({"detector_max_side": options.ocr_detector_max_side} if options.ocr_detector_max_side is not None else {}))
    except Exception as exc:
        # L'API OCR peut conserver un résultat partiel dans son exception.
        partial = getattr(exc, 'result', None)
        if isinstance(partial, dict):
            return partial
        raise ConversionFailure('ocr_failed', 'Échec de l’API OCR existante : ' + type(exc).__name__) from exc
