"""Propositions géométriques d’espacement, séparées de l’OCR brut ; aucun lexique."""


def segments(image):
    import numpy as np
    pixels = np.asarray(image.convert('L'))
    ink = pixels < 140
    occupied = ink.any(axis=0)
    xs = np.flatnonzero(occupied)
    gaps, start = [], None
    if not len(xs):
        return {'status': 'no_ink', 'segments': [], 'gaps': []}
    for x in range(int(xs[0]), int(xs[-1])+1):
        if not occupied[x] and start is None:
            start = x
        if occupied[x] and start is not None:
            gaps.append({'x0': start, 'x1': x, 'width': x-start})
            start = None
    widths = sorted({g['width'] for g in gaps})
    result = {'status': 'abstain_unclear_gaps', 'segments': [], 'gaps': gaps, 'threshold_gray': 140}
    if len(widths) < 2:
        return result
    low, high = max(zip(widths, widths[1:]), key=lambda pair: pair[1]/pair[0])
    ys = np.flatnonzero(ink.any(axis=1))
    if high/low < 3 or high < max(4, .12*(int(ys[-1])-int(ys[0])+1)):
        return result
    threshold = (low+high)/2
    edges = [int(xs[0])] + [(g['x0']+g['x1'])//2 for g in gaps if g['width'] > threshold] + [int(xs[-1])+1]
    parts = [{'x0': a, 'x1': b} for a, b in reversed(list(zip(edges, edges[1:])))]
    return dict(result, status='segmented', segments=parts, gap_threshold=threshold)


def propose(raw_text, words):
    proposed = ' '.join(w.strip() for w in words)
    accepted = (len(words) > 1 and all(w.strip() for w in words)
                and ''.join(raw_text.split()) == ''.join(proposed.split()))
    return {'accepted': accepted, 'proposed_text': proposed if accepted else None,
            'candidate_text': proposed, 'human_validated': False,
            'reason': 'geometry_and_exact_character_agreement' if accepted else 'abstain_character_mismatch_or_no_split'}
