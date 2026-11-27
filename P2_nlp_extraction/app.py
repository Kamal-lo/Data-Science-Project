"""T35 : une seule interface Streamlit locale, raccordée au pipeline réel de P2."""
import csv
from contextlib import contextmanager, nullcontext
import io
from itertools import islice
import json
import re
from pathlib import Path
import sys
import tempfile

# Streamlit exécute ce fichier comme script, depuis n'importe quel dossier.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from P2_nlp_extraction.document_ingestion import IngestionLimits
from P2_nlp_extraction.document_ingestion.safety import safe_relative
from P2_nlp_extraction.document_conversion import ConversionOptions, ConversionLimits
from P2_nlp_extraction.document_conversion.models import AUTO_LIMITS, DELIVERY_OCR_MAX_SIDE
from P2_nlp_extraction.pipeline import run_pipeline, load_job, resume_job
from P2_nlp_extraction.storage import output_path, resolve_export
from P2_nlp_extraction.scripts.ocr_common import ROOT

MAX_UPLOAD_BYTES = 25 * 1024**2


@contextmanager
def staged_upload(name, data):
    relative = safe_relative(name, IngestionLimits())
    if '/' in relative or '\\' in name or relative != name:
        raise ValueError('Un nom de fichier simple est requis.')
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError('Fichier vide ou supérieur à 25 Mio.')
    base = output_path(ROOT / 'outputs/uploads')
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as temporary:
        source = Path(temporary) / name
        source.write_bytes(data)
        yield source


def process_upload(name, data, *, pages=None, ocr_results=(), progress=None, ocr_mode=None):
    """Contrôleur de téléversement et de traitement du DCE."""
    with staged_upload(name, data) as source:
        options = upload_options(pages, ocr_results, ocr_mode)
        return run_pipeline(source, options=options, progress=progress,
                            conversion_limits=AUTO_LIMITS if options.ocr_mode == 'auto' else None)


def upload_options(pages, ocr_results=(), mode=None):
    mode = mode or ('reuse_only' if ocr_results else 'never')
    if mode == 'auto':
        import psutil
        if psutil.virtual_memory().available < 2 * 1024**3:
            raise ValueError('OCR non lancé : moins de 2 Gio de RAM physique disponible.')
    options = ConversionOptions(ocr_mode=mode, pdf_pages=pages, ocr_results=tuple(ocr_results),
                                ocr_dpi=200, ocr_batch_size=4, ocr_fallback_mode='preprocess',
                                ocr_detector_max_side=DELIVERY_OCR_MAX_SIDE)
    options.validate()
    return options


def download_bytes(entry, *, max_bytes=8 * 1024**2):
    """Refuser chemins injectés, exports remplacés et téléchargements trop gros."""
    path = resolve_export(entry, max_bytes=max_bytes)
    if path.suffix not in ('.md', '.json', '.csv', '.txt'):
        raise ValueError('Format de téléchargement refusé.')
    return path.read_bytes()


STATUS = {'completed': 'Terminé', 'completed_with_review': 'Terminé — à relire',
          'partial': 'Partiel', 'failed': 'Échec', 'processing': 'En cours',
          'not_evaluated': 'Non évalué', 'evaluated': 'Évalué', 'pending': 'En attente',
          'skipped': 'Étape ignorée', 'ocr_incomplete': 'OCR incomplet',
          'awaiting_ocr': 'En attente de lecture OCR'}
STEPS = {'storage': 'Stockage', 'ingestion': 'Lecture des fichiers', 'conversion': 'Conversion',
         'sections': 'Découpage en sections', 'tables': 'Extraction des tableaux',
         'quality': 'Évaluation de la qualité'}
WARNINGS = {
    'only_converted_pages_available': 'Seules les pages traitées figurent dans ce résultat.',
    'source_conversion_incomplete': 'La conversion couvre une partie du document ou comporte des pages incomplètes.',
    'heuristic_segmentation_not_human_validated': 'Le découpage proposé doit être relu.',
    'human_review_required_results_are_not_validated_references': 'Les résultats automatiques doivent être relus avant validation.',
    'table_and_bpu_interpretations_require_human_review': 'Vérifiez les colonnes et les valeurs des tableaux sur le document original.',
    'no_structured_table_blocks_available_not_proof_of_absence': 'Aucun tableau structuré extrait sur les pages traitées.',
    'no_dce_section_confidently_identified': 'Aucune section identifiée avec suffisamment de certitude.',
    'empty_or_unreadable_mapped_value': 'Au moins un champ est vide ou illisible.',
    'arithmetic_difference_observed_not_corrected': 'Le montant diffère du produit de la quantité par le prix unitaire.',
    'price_number_from_split_ocr_header': 'La colonne du numéro de prix a été identifiée à partir de deux fragments de son en-tête.',
}
HEADINGS = {'price_number': 'N° de prix', 'designation': 'Désignation', 'unit': 'Unité',
            'quantity': 'Quantité', 'unit_price': 'Prix unitaire', 'amount': 'Montant',
            'table_id': 'Tableau', 'row': 'Ligne', 'column': 'Colonne', 'page': 'Page',
            'value': 'Valeur', 'cell_status': 'État de la cellule', 'block_id': 'Bloc source'}


def step_name(name):
    return ' · '.join(STEPS.get(part, part) for part in name.split(':'))


def show_pages(container, pages):
    container.table([{'Page': p['page'], 'État': STATUS.get(p['status'], p['status']),
                      'Blocs': p.get('blocks', 0)} for p in pages])


def issue_text(issue):
    if isinstance(issue, dict):
        return issue.get('message') or issue_text(issue.get('code', ''))
    return WARNINGS.get(issue, f'Détail à vérifier dans le suivi ({issue}).')


def display_markdown(raw):
    text = re.sub(r'<!--\s*Page physique (\d+)\s*-->', r'**Page \1**', raw)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    return re.sub(r'<br\s*/?>', ' · ', text, flags=re.I)


def display_row(row):
    result = {}
    for key, value in row.items():
        if key in HEADINGS:
            if key == 'cell_status':
                value = {'present': 'Lue', 'covered': 'Cellule fusionnée', 'unreadable': 'Illisible',
                         'empty': 'Vide'}.get(value, value)
            result[HEADINGS[key]] = re.sub(r'<br\s*/?>|[\r\n]+', ' · ', value, flags=re.I) if value else '—'
    if 'warnings' in row:
        result['À vérifier'] = ' '.join(issue_text(w) for w in json.loads(row['warnings'])) or '—'
    return result


def main():
    import streamlit as st
    st.set_page_config(page_title='P2 — Documents DCE', layout='wide')
    st.title('P2 — Traitement des documents DCE')
    st.caption('Stockage local → fichiers → texte → sections → tableaux → évaluation')
    st.info('OCR local : jusqu’à 30 pages scannées par PDF, sous 1 536 Mio. '
            'Prévoir au moins 2 Gio disponibles. Un DCE scanné peut prendre plusieurs minutes.')
    mode = st.selectbox('Mode OCR', ['auto', 'never', 'reuse_only'],
                        format_func={'auto': 'Automatique', 'never': 'Sans OCR',
                                     'reuse_only': 'Réutiliser un résultat OCR'}.get,
                        help='auto : PaddleOCR local, seulement si le texte natif est insuffisant.')
    upload = st.file_uploader('PDF, DOCX ou ZIP — 25 Mio maximum', type=['pdf','docx','zip'],
                              max_upload_size=25)
    pages_text = st.text_input('Pages physiques PDF (vide = toutes ; exemple : 1,2)')
    cached = st.text_input('JSON OCR existant — chemin depuis la racine du dépôt (facultatif)', value='')
    previous = st.text_input('Reprendre un suivi — chemin outputs/.../job.json (facultatif)', value='')
    history = sorted((ROOT / 'outputs/runs').glob('*/job.json'),
                     key=lambda path: path.stat().st_mtime, reverse=True)[:20]
    if history:
        recent = st.selectbox('Historique local', [p.relative_to(ROOT).as_posix() for p in history], index=None)
        previous = previous.strip() or recent or ''
    revision = st.checkbox('Reprendre avec le ZIP révisé téléversé',
                           disabled=upload is None or not upload.name.lower().endswith('.zip'))
    if st.button('Ouvrir le suivi', disabled=not previous.strip()):
        try:
            st.session_state['p2_job'] = load_job(previous.strip())
        except Exception as exc:
            st.error(str(exc))
    if st.button('Reprendre le traitement', disabled=not previous.strip()):
        try:
            old = load_job(previous.strip())
            pages = (tuple(int(p.strip()) for p in pages_text.split(',')) if pages_text.strip()
                     else tuple(old['options']['pdf_pages']) if old['options'].get('pdf_pages') else None)
            options = upload_options(pages, (cached.strip(),) if cached.strip() else (), mode)
            with st.status('Reprise en cours…', expanded=True) as status:
                def show(job):
                    for value in job.get('page_progress', {}).values():
                        show_pages(st, value['pages'])
                with (staged_upload(upload.name, upload.getbuffer()) if revision and upload else nullcontext()) as source:
                    job = resume_job(previous.strip(), options=options, progress=show,
                                     conversion_limits=AUTO_LIMITS if mode == 'auto' else None,
                                     **({'source_path': source} if source else {}))
                st.session_state['p2_job'] = job
                status.update(label='Résultat : '+STATUS.get(job['status'], job['status']),
                              state='error' if job['status'] in ('failed', 'partial') else 'complete')
        except Exception as exc:
            st.error(str(exc))
    if st.button('Analyser', type='primary', disabled=upload is None):
        try:
            pages = tuple(int(p.strip()) for p in pages_text.split(',')) if pages_text.strip() else None
            with st.status('Traitement en cours…', expanded=True) as status:
                current = st.empty()
                def progress(job):
                    step = job['steps'][-1] if job['steps'] else None
                    current.write(f"{step_name(step['name'])} · {STATUS.get(step['status'], step['status'])}" if step else 'Préparation')
                    for value in job.get('page_progress', {}).values():
                        show_pages(current, value['pages'])
                job = process_upload(upload.name, upload.getbuffer(), pages=pages,
                                     ocr_results=(cached.strip(),) if cached.strip() else (), progress=progress, ocr_mode=mode)
                st.session_state['p2_job'] = job
                status.update(label='Résultat : '+STATUS.get(job['status'], job['status']), state='error' if job['status'] in ('failed', 'partial') else 'complete')
        except Exception as exc:
            st.error(str(exc))
    job = st.session_state.get('p2_job')
    if not job:
        return
    label = STATUS.get(job['status'], job['status'])
    kind = {'completed': 'success', 'completed_with_review': 'warning',
            'partial': 'warning', 'failed': 'error'}.get(job['status'], 'info')
    getattr(st, kind)(f"{label} — {job['execution_seconds']:.1f} s")
    if resume := job.get('resume'):
        st.write('Repris depuis', resume['from'], '— documents réutilisés', len(resume['reused']))
        for key, label in (('added', 'Fichiers ajoutés'), ('modified', 'Fichiers modifiés'),
                           ('removed', 'Fichiers retirés')):
            if names := resume['changes'].get(key):
                st.write(label, ', '.join(names))
    st.caption('Suivi conservé dans '+job['job_path']+' ; les étapes sont enregistrées même en cas d’erreur.')
    for value in job.get('page_progress', {}).values():
        show_pages(st, value['pages'])
    st.table([dict(Étape=step_name(s['name']), État=STATUS.get(s['status'], s['status']),
                   Secondes=round(s['seconds'],2)) for s in job['steps']])
    for step in job['steps']:
        for issue in step['errors']:
            st.warning(issue_text(issue))
        if step.get('warnings'):
            with st.expander('Avertissements — '+step_name(step['name'])):
                for issue in step['warnings']:
                    st.write(issue_text(issue))
    for issue in job['errors'] + job['warnings']:
        st.warning(issue_text(issue))
    for document in job['documents']:
        with st.expander(document['document_id']+' — '+STATUS.get(document['status'], document['status']), expanded=True):
            st.caption(str(document['source'].get('original_name','')))
            exports = dict(document['outputs'])
            text_tab, sections_tab, tables_tab, downloads_tab = st.tabs(
                ['Texte', 'Sections', 'Tableaux et BPU', 'Téléchargements'])
            with text_tab:
                if 'document_md' in exports:
                    try:
                        st.markdown(display_markdown(download_bytes(exports['document_md']).decode('utf-8')), unsafe_allow_html=False)
                    except (OSError, ValueError) as exc:
                        st.warning(str(exc))
                else:
                    st.info('Aucun texte exporté pour ce document.')
                if 'document_json' in exports and st.checkbox('Repères et éléments graphiques',
                                                               key=document['document_id']+'_locators'):
                    try:
                        details = json.loads(download_bytes(exports['document_json'],
                                                            max_bytes=AUTO_LIMITS.max_output_bytes))
                        locators = details.get('text_locators', [])[:20]
                        if locators:
                            st.markdown('**Dates et références repérées**')
                            st.dataframe([{'Page': v['page'], 'Mention': v['raw_text'],
                                           'Bloc source': v['block_id'], 'Coordonnées': v['bbox']}
                                          for v in locators], hide_index=True)
                        graphics = (dict(graphic, page=page['page']) for page in details['pages']
                                    for graphic in page.get('graphics', []))
                        preview = list(islice(graphics, 20))
                        if preview:
                            st.markdown('**Éléments graphiques**')
                            st.dataframe([{'Page': v['page'], 'Type': 'Image' if v['kind'] == 'raster' else 'Tracé vectoriel',
                                           'Indice source': v['index'], 'Coordonnées': v['bbox']}
                                          for v in preview], hide_index=True)
                        if not locators and not preview:
                            st.caption('Aucun repère ni élément graphique disponible.')
                    except (OSError, ValueError) as exc:
                        st.warning(str(exc))
            with sections_tab:
                try:
                    if 'sections_md' in exports:
                        st.markdown('#### Sections détectées')
                        st.markdown(display_markdown(download_bytes(exports['sections_md']).decode('utf-8')))
                except (OSError, ValueError, csv.Error) as exc:
                    st.warning(str(exc))
            with tables_tab:
                try:
                    for key, title in (('tables_csv', 'Cellules des tableaux'), ('bpu_csv', 'Lignes de prix BPU')):
                        if key in exports:
                            rows = csv.DictReader(io.StringIO(download_bytes(exports[key]).decode('utf-8-sig')),
                                                  delimiter=';')
                            preview = list(islice(rows, 20))
                            total = len(preview) + sum(1 for _ in rows)
                            st.metric(title, total)
                            if preview:
                                st.dataframe([display_row(row) for row in preview], hide_index=True)
                except (OSError, ValueError, csv.Error) as exc:
                    st.warning(str(exc))
            with downloads_tab:
                for index, quality in enumerate(document['quality']):
                    for lang, status in quality['ocr_status'].items():
                        st.caption(f"OCR ({lang}) · {STATUS.get(status, status)}")
                    status = quality['segmentation_status']
                    st.caption(f"Découpage · {STATUS.get(status, status)}")
                    exports.update({f'quality_{index}_{key}':value for key,value in quality['outputs'].items()})
                name = st.selectbox('Export à télécharger', list(exports), index=None,
                                    key=document['document_id']+'_export')
                if name:
                    entry = exports[name]
                    try:
                        st.download_button('Télécharger',download_bytes(entry, max_bytes=AUTO_LIMITS.max_output_bytes),
                                           file_name=document['document_id']+'_'+Path(entry['path']).name,
                                           key=document['document_id']+'_'+name)
                    except (OSError, ValueError) as exc:
                        st.warning(str(exc))


if __name__ == '__main__':
    main()
