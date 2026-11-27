"""Exact root-section evaluation: no fuzzy matching or guessed human labels."""
CATEGORIES=('RC','CPS','CCAP','CCTP','BPU')


def prf(tp,fp,fn):
    return dict(true_positives=tp,false_positives=fp,false_negatives=fn,
                precision=tp/(tp+fp) if tp+fp else None,
                recall=tp/(tp+fn) if tp+fn else None,
                f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)


def compare_sections(predicted, references):
    """Inputs are already confined to a human-annotated, exhaustive block scope."""
    key=lambda s:(s['category'],s['start_block_id'],s['end_block_id'])
    span=lambda s:(s['start_block_id'],s['end_block_id'])
    p={key(s) for s in predicted};r={key(s) for s in references}
    ps={span(s) for s in predicted};rs={span(s) for s in references}
    exact=prf(len(p&r),len(p-r),len(r-p))
    boundary=prf(len(ps&rs),len(ps-rs),len(rs-ps))
    common=ps&rs
    correct=sum(any(key(s) in r for s in predicted if span(s)==pair) for pair in common)
    categories=dict(correct=correct,compared=len(common),accuracy=correct/len(common) if common else None)
    per_category={c:prf(len({v for v in p&r if v[0]==c}),len({v for v in p-r if v[0]==c}),
                        len({v for v in r-p if v[0]==c})) for c in CATEGORIES}
    errors=[]
    for section in references:
        if key(section) in p:continue
        reason='category_error' if span(section) in ps else 'missing_or_incorrect_boundaries'
        errors.append(dict(kind=reason,reference=section))
    for section in predicted:
        if key(section) not in r:errors.append(dict(kind='false_positive_or_incorrect_section',prediction=section))
    return dict(labeled_exact=exact,boundary_exact=boundary,category_on_exact_spans=categories,
                boundary_exact_accuracy=len(common)/len(rs) if rs else None,
                per_category=per_category,errors=errors)


def compare_hierarchy(roots, references, positions, scope, max_nodes):
    """Score annotated article/subsection intervals independently of roots."""
    def key(kind, start, end):
        return kind, start, end

    annotated = {key(r['kind'], r['start_block_id'], r['end_block_id']) for r in references}
    if (len(annotated) != len(references) or len(annotated) > max_nodes
            or any(a not in scope or b not in scope or positions[a] > positions[b] for _, a, b in annotated)):
        raise ValueError('Annotations des articles ou sous-sections incohérentes.')
    predicted = set()
    pending = [child for root in roots for child in root['children']]
    seen = 0
    while pending:
        node = pending.pop()
        seen += 1
        if seen > max_nodes:
            raise ValueError('Trop d’articles ou sous-sections prédits.')
        pending.extend(node['children'])
        blocks = node['source_block_ids']
        if blocks and scope.intersection(blocks):
            if not set(blocks) <= scope:
                raise ValueError('Un article ou une sous-section traverse le périmètre annoté.')
            predicted.add(key(node['kind'], blocks[0], blocks[-1]))
    metrics = {}
    for kind in ('article', 'subsection'):
        p = {x[1:] for x in predicted if x[0] == kind}
        r = {x[1:] for x in annotated if x[0] == kind}
        metrics[kind] = {**prf(len(p & r), len(p - r), len(r - p)),
                         'missing_boundaries': sorted(r - p), 'extra_boundaries': sorted(p - r)}
    return metrics
