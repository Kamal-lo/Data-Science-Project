"""Unicode code-point Levenshtein, linear memory, deterministic edit counts."""
import unicodedata


def _normalize(text, normalization):
    if not isinstance(text, str):
        raise TypeError('Textes requis.')
    if normalization not in ('none', 'NFC'):
        raise ValueError('Normalisation : none ou NFC.')
    return unicodedata.normalize('NFC', text) if normalization == 'NFC' else text


def _edit_counts(left, right, max_alignment_cells):
    """Resolve equal-cost edits in diagonal, deletion, insertion order."""
    if (len(left)+1)*(len(right)+1)>max_alignment_cells:raise ValueError('alignment_budget_exceeded')
    if not left:return None
    previous=[(j,0,j,0) for j in range(len(right)+1)]
    for i,a in enumerate(left,1):
        current=[(i,0,0,i)]
        for j,b in enumerate(right,1):
            cost,s,ins,deletions=previous[j-1]
            diagonal=(cost+(a!=b),s+(a!=b),ins,deletions)
            cost,s,ins,deletions=previous[j]
            deletion=(cost+1,s,ins,deletions+1)
            cost,s,ins,deletions=current[-1]
            insertion=(cost+1,s,ins+1,deletions)
            current.append(min((diagonal,deletion,insertion),key=lambda x:x[0]))
        previous=current
    total, substitutions, insertions, deletions = previous[-1]
    return dict(substitutions=substitutions, insertions=insertions,
                deletions=deletions, total_errors=total)


def character_errors(reference, hypothesis, *, normalization='none', max_alignment_cells=8000000):
    """Calculate character errors independently of reference approval."""
    left, right = (_normalize(text, normalization) for text in (reference, hypothesis))
    counts = _edit_counts(left, right, max_alignment_cells)
    if counts is None:
        return None
    total = counts['total_errors']
    return dict(**counts,
                reference_characters=len(left),hypothesis_characters=len(right),
                cer=total/len(left),cer_percent=100*total/len(left),normalization=normalization,
                reference_changed=left!=reference,hypothesis_changed=right!=hypothesis)


def word_errors(reference, hypothesis, *, normalization='none', max_alignment_cells=8000000):
    """Calculate WER on whitespace-delimited words, retaining punctuation and diacritics."""
    left, right = (_normalize(text, normalization).split() for text in (reference, hypothesis))
    counts = _edit_counts(left, right, max_alignment_cells)
    if counts is None:
        return None
    return dict(counts, reference_words=len(left), hypothesis_words=len(right),
                wer=counts['total_errors'] / len(left),
                wer_percent=100 * counts['total_errors'] / len(left))
