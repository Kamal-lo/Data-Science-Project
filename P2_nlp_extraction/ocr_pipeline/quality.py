"""Garde-fous reproductibles, pas de score d'exactitude ou de vérité terrain."""
from collections import Counter
import unicodedata

from .routing import RULES, script_stats

QUALITY_POLICY = {'version': 'p2.ocr_quality.v1', 'calibrated': False,
                  'confidence_thresholds': {'fr': RULES['fr_min_score'], 'ar': RULES['ar_min_score']},
                  'maximum_repeated_character_fraction': .75, 'minimum_repetition_length': 6,
                  'human_validated': False}


def assess(result):
    """usable signifie seulement : admissible pour l'extraction automatique."""
    text = result.get('raw_text')
    candidates = result.get('recognition_candidates', {})
    reason = result.get('routing_reason')
    reasons, action = [], 'none'
    if reason in ('conflicting_plausible_scripts', 'mixed_script_candidate_requires_review'):
        reasons.append('ambiguous_scripts'); action = 'review_only'
    elif text is None or not str(text).strip():
        reasons.append('no_selected_text'); action = 'retry'
        fr = script_stats(candidates.get('fr', {}).get('text', ''))
        ar = script_stats(candidates.get('ar', {}).get('text', ''))
        if (fr['script'] == 'neutral' and ar['script'] in ('latin', 'mixed_or_other')) or fr['other'] or ar['other']:
            reasons.append('unsupported_or_unknown_script_risk'); action = 'review_only'
    else:
        visible = [c for c in text if not c.isspace()]
        bad = any(c == '\ufffd' or unicodedata.category(c) in ('Co', 'Cc', 'Cs') for c in visible)
        letters = [c.casefold() for c in visible if c.isalpha()]
        repeated = (len(letters) >= QUALITY_POLICY['minimum_repetition_length']
                    and Counter(letters).most_common(1)[0][1] / len(letters) >= .75)
        if bad: reasons.append('suspect_unicode')
        if repeated: reasons.append('repeated_character_noise')
        if result.get('language') == 'und':
            neutral_ok = (any(c.isdigit() for c in text)
                          and all(not candidates.get(lang, {}).get('error')
                                  and candidates.get(lang, {}).get('confidence', 0) >= RULES[lang + '_min_score']
                                  for lang in ('fr', 'ar')))
            if not neutral_ok:
                reasons.append('neutral_consensus_not_reliable'); action = 'review_only'
        if reasons and action == 'none': action = 'retry'
    errors = any(c.get('error') for c in candidates.values())
    if errors and action == 'none': action = 'retry'
    return {'usable': not reasons, 'reasons': reasons, 'action': action,
            'recognizer_errors': errors, 'heuristic': True, 'human_validated': False,
            'policy_version': QUALITY_POLICY['version']}


def page_summary(blocks):
    return {'policy_version': QUALITY_POLICY['version'], 'calibrated': False,
            'blocks': len(blocks), 'unresolved_blocks': sum(b.get('raw_text') is None for b in blocks),
            'quality_rejected_blocks': sum(not b.get('quality', {}).get('usable', False) for b in blocks),
            'fallback_attempted_blocks': sum(bool(b.get('fallback_attempted')) for b in blocks),
            'fallback_selected_blocks': sum(bool(b.get('fallback_used')) for b in blocks),
            'human_validated': False}
