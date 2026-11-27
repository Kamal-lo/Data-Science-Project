"""Règles expérimentales de routage : aucune comparaison directe des confiances."""
import unicodedata

RULES = {'version': 'script_rules.v1', 'fr_min_score': 0.80, 'ar_min_score': 0.75,
         'script_dominance': 0.80, 'minimum_letters': 2, 'calibrated': False}


def script_stats(text):
    counts = {'arabic': 0, 'latin': 0, 'other': 0}
    for char in text:
        if not char.isalpha():
            continue
        name = unicodedata.name(char, '')
        key = 'arabic' if 'ARABIC' in name else 'latin' if 'LATIN' in name else 'other'
        counts[key] += 1
    total = sum(counts.values())
    if not total:
        script = 'neutral'
    elif counts['arabic'] / total >= RULES['script_dominance']:
        script = 'arabic'
    elif counts['latin'] / total >= RULES['script_dominance']:
        script = 'latin'
    else:
        script = 'mixed_or_other'
    return dict(counts, letters=total, script=script)


def route(candidates):
    """Choix d’un candidat brut ou abstention ; jamais de réécriture de son texte."""
    analyzed = {}
    for lang in ('fr', 'ar'):
        value = candidates.get(lang, {'text': '', 'confidence': 0, 'error': 'candidate_missing'})
        analyzed[lang] = dict(value, script_analysis=script_stats(value['text']))
    fr, ar = analyzed['fr'], analyzed['ar']
    credible = {}
    for lang, value, expected in [('fr', fr, 'latin'), ('ar', ar, 'arabic')]:
        stats = value['script_analysis']
        credible[lang] = (not value.get('error') and stats['script'] == expected
                          and stats['letters'] >= RULES['minimum_letters']
                          and value['confidence'] >= RULES[lang+'_min_score'])
    selected, language, reason = None, 'und', 'no_reliable_script_candidate'
    warnings = []
    if credible['fr'] and credible['ar']:
        reason = 'conflicting_plausible_scripts'
    elif credible['ar']:
        selected, language, reason = 'ar', 'ar', 'dominant_arabic_script_in_ar_model'
    elif credible['fr']:
        selected, language, reason = 'fr', 'fr', 'latin_script_assumed_french_in_target_pair'
        if (ar['script_analysis']['script'] == 'latin' and ar['confidence'] >= RULES['ar_min_score']
                and ar['text'] != fr['text']):
            warnings.append('latin_recognizers_disagree')
    elif (fr['text'].strip() and fr['text'] == ar['text']
          and fr['script_analysis']['script'] == 'neutral' and not fr.get('error') and not ar.get('error')):
        selected, reason = 'fr', 'neutral_exact_consensus_language_unknown'
    elif ar['script_analysis']['arabic'] >= 2 and ar['script_analysis']['latin'] >= 2:
        language, reason = 'mixed', 'mixed_script_candidate_requires_review'
    if any(value.get('error') for value in analyzed.values()):
        warnings.append('recognizer_error')
    raw = analyzed[selected]['text'] if selected else None
    return {'language': language, 'script': script_stats(raw or '')['script'],
            'selected_candidate': selected, 'raw_text': raw,
            'routing_reason': reason, 'recognition_candidates': analyzed,
            'needs_review': selected is None or bool(warnings), 'warnings': warnings,
            'language_basis': 'uncalibrated_target_pair_script_heuristic'}
