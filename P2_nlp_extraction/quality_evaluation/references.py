"""Read reference artifacts and recorded OCR; never promote OCR into ground truth."""
import hashlib
import json
from datetime import datetime
from pathlib import Path


# Actual ocr_pipeline worker/API states, not T24 conversion states. A partial
# document may contain finalized pages; an in-progress document is not frozen.
FINAL_OCR_DOCUMENT_STATES = frozenset(('completed', 'completed_with_review', 'partial'))
FINAL_OCR_PAGE_STATES = frozenset(('ok', 'needs_review', 'no_text_detected'))


def scope_hash(scope):
    return hashlib.sha256(json.dumps(scope,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()


def approved(approval):
    if not isinstance(approval.get('approved_at'),str):return False
    try:
        stamp=datetime.fromisoformat(approval.get('approved_at','').replace('Z','+00:00'))
    except (ValueError,TypeError):return False
    return (approval.get('human_reviewed') is True and approval.get('scope_confirmed') is True
            and isinstance(approval.get('reviewer'),str) and bool(approval['reviewer'].strip())
            and stamp.tzinfo is not None)


def references(manifest, read, dataset_kind='real'):
    """Return records, keeping validation failures as explicit blockers."""
    legacy=manifest.get('protocol')=='precision.pages_1_2.v1'
    if not legacy and manifest.get('schema_version')!='p2.ocr_references.v1':raise ValueError('Format de références OCR inconnu.')
    records=[]
    for item in manifest['pages'] if legacy else manifest['records']:
        approval=item.get('approval') or {}
        scope=manifest['evaluation_scope'] if legacy else item.get('scope')
        digest=scope_hash(scope)
        blockers=[]
        scoped=scope.get('pages',{}).get(str(item['page'])) if legacy and isinstance(scope,dict) else scope
        try:
            width,height=scoped['image_size']
            boxes=[r['bbox'] for r in scoped['regions']]
            if not boxes or not all(0<=a<c<=width and 0<=b<d<=height for a,b,c,d in boxes):
                blockers.append('invalid_reference_geometry')
        except (KeyError,TypeError,ValueError):blockers.append('invalid_reference_geometry')
        synthetic=dataset_kind=='synthetic' and manifest.get('dataset_kind')=='synthetic'
        if not synthetic and not approved(approval):blockers.append('reference_not_human_validated')
        if approval.get('scope_sha256')!=digest:blockers.append('scope_hash_mismatch')
        if legacy and manifest.get('scope_sha256')!=digest:blockers.append('scope_hash_mismatch')
        text=None;reference_path=approval.get('reference_file')
        reference_digest=approval.get('reference_sha256')
        if not reference_path:blockers.append('reference_missing')
        else:
            try:
                raw=read(reference_path)
                if hashlib.sha256(raw).hexdigest()!=reference_digest:blockers.append('reference_hash_mismatch')
                else:text=raw.decode('utf-8')
            except (OSError,ValueError,UnicodeError):blockers.append('reference_missing_or_inaccessible')
        document_hash=manifest.get('source_hashes',{}).get('data/pdf/test_dce.pdf') if legacy else manifest.get('document_sha256')
        records.append(dict(page=item['page'],language='fr' if legacy else item['language'],
                            reference_text=text,reference_source=reference_path,reference_sha256=reference_digest,
                            approval=approval,scope_sha256=digest,scope=scope,legacy=legacy,
                            document_sha256=document_hash,blockers=list(dict.fromkeys(blockers))))
    return records


def coverage(box,regions):
    """Exact area of rectangle union clipped to one block (overlaps counted once)."""
    x0,y0,x1,y1=box
    if x1<=x0 or y1<=y0:raise ValueError('Invalid block box')
    clipped=[(max(x0,a),max(y0,b),min(x1,c),min(y1,d)) for a,b,c,d in regions]
    clipped=[r for r in clipped if r[2]>r[0] and r[3]>r[1]]
    xs=sorted({v for a,b,c,d in clipped for v in (a,c)})
    area=0
    for left,right in zip(xs,xs[1:]):
        intervals=sorted((b,d) for a,b,c,d in clipped if a<=left and c>=right)
        end=None;length=0
        for low,high in intervals:
            if end is None or low>end:length+=high-low;end=high
            elif high>end:length+=high-end;end=high
        area+=(right-left)*length
    return area/((x1-x0)*(y1-y0))


def hypothesis(document,reference):
    blockers=[];selected=[]
    pages=[p for p in document['pages'] if p['page']==reference['page']]
    if len(pages)!=1:return None,[],['ocr_page_missing_or_duplicate']
    page=pages[0]
    if document.get('status') not in FINAL_OCR_DOCUMENT_STATES:
        blockers.append('ocr_document_not_finalized')
    if page.get('status') not in FINAL_OCR_PAGE_STATES:
        blockers.append('ocr_page_not_finalized')
    if page.get('status') in ('error','failed') or page.get('errors'):blockers.append('ocr_page_failed')
    scope=reference['scope']
    scoped=scope.get('pages',{}).get(str(reference['page'])) if reference['legacy'] else scope
    if not scoped:return None,[],['reference_scope_missing']
    if page.get('dpi')!=(200 if reference['legacy'] else scoped.get('dpi')) or page.get('image_size')!=scoped.get('image_size'):
        blockers.append('ocr_geometry_does_not_match_reference_scope')
    if document.get('pdf_sha256')!=reference['document_sha256']:blockers.append('document_hash_mismatch')
    regions=[r['bbox'] for r in scoped['regions']]
    for block in page['blocks']:
        box=block.get('bbox')
        if not isinstance(box,list) or len(box)!=4:blockers.append('missing_block_geometry');continue
        fraction=coverage(box,regions)
        if fraction<=1e-8:continue
        if fraction<1-1e-8:
            blockers.extend(['block_crosses_validated_scope_boundary','crossing_block:'+block['block_id']]);continue
        if not isinstance(block.get('raw_text'),str):
            blockers.extend(['unresolved_text_in_scope','unresolved_block:'+block['block_id']]);continue
        selected.append(block)
    # Preserve recorded block order and separate blocks by a literal LF.
    return '\n'.join(b['raw_text'] for b in selected),[b['block_id'] for b in selected],list(dict.fromkeys(blockers))
