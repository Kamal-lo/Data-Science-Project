"""Repli borné avec les mêmes modèles ; toutes les hypothèses sont conservées."""
from time import perf_counter
import math

from .preprocessing import enhance_scan
from .quality import assess
from .routing import route


class FallbackBudget:
    def __init__(self, mode='off', max_blocks=8, timeout_seconds=20, observer=None):
        self.mode, self.max_blocks, self.timeout_seconds = mode, max_blocks, timeout_seconds
        self.blocks_attempted, self.page_attempted, self.spent_seconds = 0, False, 0.0
        self.observer = observer

    def begin(self, kind, primary=None):
        if self.observer:
            self.observer('begin', kind, max(0, self.timeout_seconds - self.spent_seconds), primary)

    def finish(self, kind):
        if self.observer:
            self.observer('finish', kind, max(0, self.timeout_seconds - self.spent_seconds), None)

    def reserve(self, kind):
        if self.mode == 'off': return 'disabled'
        if self.spent_seconds >= self.timeout_seconds: return 'fallback_time_budget'
        if kind == 'page':
            if self.page_attempted: return 'page_alternative_already_attempted'
            self.page_attempted = True
        else:
            if self.blocks_attempted >= self.max_blocks: return 'fallback_block_budget'
            self.blocks_attempted += 1
        return None

    def report(self):
        return {'mode': self.mode, 'blocks_attempted': self.blocks_attempted,
                'page_attempted': self.page_attempted, 'spent_seconds': self.spent_seconds,
                'max_blocks': self.max_blocks, 'timeout_seconds': self.timeout_seconds,
                'time_limit_checked_between_attempts': True,
                'active_attempt_supervised': self.observer is not None}


def _error(stage, exc):
    return {'stage': stage, 'type': type(exc).__name__, 'message': str(exc)}


def recognize_candidates(backend, crop):
    candidates, errors, timings = {}, [], {}
    for lang in ('fr', 'ar'):
        started = perf_counter()
        value = None
        try:
            if crop is None:
                raise ValueError('Recadrage du bloc indisponible.')
            value = backend.recognize(crop, lang)
            if not isinstance(value, dict) or not isinstance(value.get('text'), str):
                raise ValueError('Candidat OCR mal formé.')
            score = value.get('confidence')
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError('Confiance OCR invalide.')
            candidates[lang] = dict(value)
            if value.get('error'):
                errors.append({'stage': 'recognition_' + lang, 'type': 'RecognizerError', 'message': str(value['error'])})
        except Exception as exc:
            raw = value.get('text') if isinstance(value, dict) else None
            candidates[lang] = {'text': raw if isinstance(raw, str) else '', 'confidence': 0, 'error': str(exc)}
            if isinstance(value, dict) and 'confidence' in value:
                candidates[lang]['invalid_confidence_repr'] = repr(value['confidence'])
            errors.append(_error('recognition_' + lang, exc))
        timings['recognition_' + lang + '_seconds'] = perf_counter() - started
    return candidates, errors, timings


def recognize_block(backend, crop, budget, max_pixels, *, image_variant='original'):
    candidates, errors, timings = recognize_candidates(backend, crop)
    started_routing = perf_counter()
    primary = route(candidates)
    quality = assess(primary)
    timings['routing_seconds'] = perf_counter() - started_routing
    attempts = [{'variant': image_variant, 'result': primary, 'quality': quality,
                 'errors': errors, 'timings': dict(timings)}]
    selected, skipped, selected_errors = 0, None, errors
    warnings = []
    if quality['action'] == 'review_only':
        skipped = 'ambiguous_or_unsupported_region_requires_review'
    elif quality['action'] == 'retry':
        if crop is None: skipped = 'crop_unavailable'
        elif image_variant != 'original': skipped = 'page_already_preprocessed'
        else: skipped = budget.reserve('block')
        if skipped is None:
            started = perf_counter()
            budget.begin('block', _selected(attempts, 0, primary, quality, [], None))
            try:
                processed, metadata = enhance_scan(crop, max_pixels)
                alternative, alt_errors, alt_times = recognize_candidates(backend, processed)
                started_routing = perf_counter()
                alternate_result = route(alternative)
                alternate_quality = assess(alternate_result)
                alt_times['routing_seconds'] = perf_counter() - started_routing
                attempts.append({'variant': 'contrast_grayscale', 'preprocessing': metadata,
                                 'result': alternate_result, 'quality': alternate_quality,
                                 'errors': alt_errors, 'timings': alt_times})
                for key, value in alt_times.items(): timings[key] += value
                compatible = not quality['usable'] or (alternate_result['raw_text'] == primary['raw_text']
                                                       and alternate_result['language'] == primary['language'])
                if alternate_quality['usable'] and not alternate_quality['recognizer_errors'] and compatible:
                    selected, selected_errors = 1, alt_errors
                elif quality['usable'] and alternate_quality['usable'] and not compatible:
                    warnings.append('fallback_conflicts_with_primary_primary_preserved')
            except Exception as exc:
                attempts.append({'variant': 'contrast_grayscale', 'errors': [_error('fallback', exc)], 'result': None})
                warnings.append('fallback_failed_primary_preserved')
            finally:
                budget.spent_seconds += perf_counter() - started
                budget.finish('block')
    final = _selected(attempts, selected, primary, attempts[selected]['quality'], warnings, skipped)
    return final, selected_errors, timings


def _selected(attempts, selected, primary, selected_quality, warnings, skipped):
    final = dict(attempts[selected]['result'])
    final['warnings'] = list(final['warnings']) + warnings
    if not selected_quality['usable']:
        final.update(raw_text=None, selected_candidate=None, language='und', script='neutral',
                     routing_reason='quality_gate_abstention', needs_review=True)
        final['warnings'].append('quality_gate_requires_human_review')
    if selected:
        final['warnings'].append('preprocessed_fallback_selected_unvalidated')
        final['needs_review'] = True
    final.update(primary_raw_text=primary['raw_text'], recognition_attempts=attempts,
                 selected_attempt=selected, fallback_attempted=len(attempts) > 1,
                 fallback_used=bool(selected), fallback_skipped_reason=skipped,
                 quality=selected_quality)
    return final


def detect_page(backend, bgr, budget, max_pixels, *, image_variant='original'):
    """Au plus un nouveau passage détecteur, dans le même repère de pixels."""
    attempts, selected_error = [], None
    try:
        polygons, scores = backend.detect(bgr)
        attempts.append({'variant': image_variant, 'detection_count': len(polygons), 'error': None})
    except Exception as exc:
        polygons, scores, selected_error = [], [], _error('detection', exc)
        attempts.append({'variant': image_variant, 'detection_count': 0, 'error': selected_error})
    processed, metadata, selected = bgr, None, 0
    skipped = None
    if not len(polygons):
        skipped = 'page_already_preprocessed' if image_variant != 'original' else budget.reserve('page')
        if skipped is None:
            started = perf_counter()
            budget.begin('detection', {'attempts': list(attempts), 'selected_attempt': 0,
                                      'selected_error': selected_error})
            try:
                alternate, metadata = enhance_scan(bgr, max_pixels)
                alt_polys, alt_scores = backend.detect(alternate)
                attempts.append({'variant': 'contrast_grayscale', 'detection_count': len(alt_polys),
                                 'preprocessing': metadata, 'error': None})
                if len(alt_polys):
                    polygons, scores, processed, selected, selected_error = alt_polys, alt_scores, alternate, 1, None
            except Exception as exc:
                attempts.append({'variant': 'contrast_grayscale', 'error': _error('detection_fallback', exc)})
                if selected_error is None: selected_error = _error('detection_fallback', exc)
            finally:
                budget.spent_seconds += perf_counter() - started
                budget.finish('detection')
    return polygons, scores, processed, {'attempts': attempts, 'selected_attempt': selected,
                                        'skipped_reason': skipped, 'selected_error': selected_error,
                                        'selected_preprocessing': metadata if selected else None}
