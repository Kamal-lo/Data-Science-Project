"""Décision par page, heuristique documentée ; jamais un score de qualité validé."""
import unicodedata
from .layout import area, intersection


def native_quality(text):
    visible = [c for c in text if not c.isspace()]
    bad = sum(c == '\ufffd' or unicodedata.category(c) in ('Co', 'Cc', 'Cs') for c in visible)
    return {'visible_characters': len(visible), 'suspect_characters': bad,
            'suspect_ratio': bad / max(1, len(visible)),
            'usable': bool(visible) and bad / max(1, len(visible)) < .05}


def choose_route(blocks, images, page_box, ink_without_text=False):
    text = '\n'.join(b['raw_text'] or '' for b in blocks)
    quality = native_quality(text)
    uncovered = []
    for image in images:
        # Une image substantielle sans couche de texte doit pouvoir passer en OCR,
        # même si un pied de page natif existe ailleurs.
        covered = sum(intersection(image, b['bbox']) for b in blocks if b.get('native_usable', True))
        fraction = min(1, covered / max(1, area(image)))
        if area(image) / max(1, area(page_box)) >= .08 and fraction < .15:
            uncovered.append(image)
    if any(b.get('native_usable') is False for b in blocks):
        has_usable = any(b.get('native_usable', True) for b in blocks)
        decision = 'hybrid' if has_usable else 'ocr'
        reason = 'native_blocks_unusable' if has_usable else 'native_text_unusable'
    elif not quality['usable'] and quality['visible_characters']:
        decision, reason = 'ocr', 'native_text_unusable'
    elif uncovered:
        decision, reason = 'hybrid' if quality['usable'] else 'ocr', 'substantial_image_without_text_layer'
    elif quality['usable'] and quality['visible_characters'] < 30:
        decision, reason = 'hybrid', 'sparse_native_text_requires_visual_check'
    elif quality['usable']:
        decision, reason = 'native', 'native_text_usable'
    elif ink_without_text or images:
        decision, reason = 'ocr', 'visual_content_without_text'
    else:
        decision, reason = 'blank', 'apparently_blank_page'
    return dict(decision=decision, reason=reason, native_quality=quality,
                uncovered_image_regions=uncovered, heuristic=True,
                warnings=['routing_is_heuristic_not_quality_validation'])
