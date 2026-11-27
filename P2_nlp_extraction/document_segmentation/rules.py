"""Dictionnaire explicite, comparaison normalisée uniquement, scores non calibrés."""
import re
import unicodedata

VERSION = 'p2.dce_title_rules.v1'


def normalize(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c) and c != '\u0640')
    return ' '.join(re.sub(r'[^\w\s]', ' ', text).split())


TITLES = {
    'RC': ['règlement de consultation', 'règlement de la consultation', 'règlement consultation',
           'نظام الاستشارة', 'نظام طلب العروض'],
    'CPS': ['cahier des prescriptions spéciales', 'cahier de prescriptions spéciales',
            'دفتر الشروط الخاصة'],
    'CCAP': ['cahier des clauses administratives particulières', 'دفتر الشروط الإدارية الخاصة'],
    'CCTP': ['cahier des clauses techniques particulières', 'دفتر الشروط التقنية الخاصة'],
    'BPU': ['bordereau des prix unitaires', 'bordereau de prix unitaires',
            'bordereau des prix - détail estimatif',
            'جدول الأثمان الوحدوية', 'جدول الأسعار الوحدوية'],
}
ALIASES = {category: {normalize(t) for t in values} for category, values in TITLES.items()}


def title_matches(text):
    """Only an entire short title can become a boundary; never a prose mention."""
    text = re.sub(r'\.{2,}\s*\d+\s*$', '', text)
    value = normalize(text)
    if value not in {' '.join(c.casefold()) for c in TITLES}:
        value = re.sub(r'^(?:(?:annexe|partie|section)\s+)?(?:\d+|[ivxlcdm]+)\s+', '', value)
    exact = []
    for category, aliases in ALIASES.items():
        acronym = normalize(category)
        dotted = ' '.join(category.casefold())
        forms = aliases | {acronym, dotted}
        if value in forms or any(value == a+' '+acronym or value == acronym+' '+a for a in aliases):
            exact.append(category)
    if exact: return exact, value in {normalize(c) for c in exact} | {' '.join(c.casefold()) for c in exact}
    # A compound *short heading* is an ambiguous candidate, never a chosen class.
    if len(text) <= 220:
        found = [c for c, aliases in ALIASES.items() if any(a in value for a in aliases)
                 or re.search(r'(?<!\w)'+c.casefold()+r'(?!\w)', value)]
        if len(found) > 1: return found, False
    return [], False


ARTICLE = re.compile(r'^\s*(?:article|art\.|المادة|الفصل)\s+'
                     r'(\d+(?:\.\d+)*|[ivxlcdm]+|premier|unique|1er|الأول|الاول|الوحيد)'
                     r'(?=\s|[:.\-–—]|$)(.*)$', re.I)
NUMBERED = re.compile(r'^\s*(\d+(?:\.\d+)+)[.)]?\s+\S')
TOC = {'sommaire', 'table des matieres', 'table des matieres du dossier', 'فهرس', 'المحتويات'}


def article(text, heading=False):
    match = ARTICLE.match(text)
    if not match or len(text) > 200: return None
    tail = match[2].strip()
    reliable = heading or not tail or tail[0] in ':.-–—' or text.isupper()
    return {'number': match[1], 'reliable': reliable}


def masked_fragment(block):
    """T24 retains masked fragments for provenance, not structure or rendering.

    A table itself is retained; its explicitly represented fragments are not
    rendered a second time. Do not infer membership from geometric overlap.
    """
    return block['type'] != 'table' and (
        block.get('render') is False or 'represented_in_table' in block.get('warnings', []))
