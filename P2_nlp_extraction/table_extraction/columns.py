"""Matching of headers only. Never normalize the exported source values."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

FIELDS = ('price_number', 'designation', 'unit', 'quantity', 'unit_price', 'amount')


def normalize(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', value or '').casefold()
                    if not unicodedata.combining(c) and c != '\u0640')
    return ' '.join(re.sub(r'[^\w\s]', ' ', value).split())


ALIASES = {
    'price_number': ['n°', 'n° prix', 'prix n°', 'n° de prix', 'numéro de prix', 'numéro du prix', 'numéro', 'n prix', 'n de prix', 'n', 'رقم', 'رقم الثمن', 'رقم السعر'],
    'designation': ['désignation', 'désignation des prestations', 'désignation des ouvrages', 'désignation des travaux', 'libellé', 'بيان', 'التعيين', 'بيان الأشغال', 'وصف الخدمات'],
    'unit': ['unité', 'unité de mesure', 'u', 'الوحدة', 'وحدة', 'وحدة القياس'],
    'quantity': ['quantité', 'quantités', 'qté', 'qte', 'qt', 'الكمية', 'كمية'],
    'unit_price': ['prix unitaire', 'prix unitaires', 'prix unitaire ht', 'p.u.', 'pu', 'p u ht', 'p.u. (h.t)', 'الثمن الوحدوي', 'السعر الوحدوي', 'سعر الوحدة'],
    'amount': ['montant', 'montant ht', 'montant total', 'prix total', 'total', 'p.t. (h.t)', 'المبلغ', 'المبلغ الإجمالي', 'الثمن الإجمالي'],
}
ALIASES = {key: {normalize(v) for v in values} for key, values in ALIASES.items()}


def header_columns(row):
    columns = []
    for index, label in enumerate(row):
        value = normalize(label)
        matches = [key for key, aliases in ALIASES.items() if value in aliases]
        if value == 'prix': matches = ['unit_price', 'amount']
        columns.append(dict(index=index, header_raw=label, candidates=matches,
                            field=matches[0] if len(matches)==1 else None))
    duplicates = {c['field'] for c in columns if c['field'] and
                  sum(other['field']==c['field'] for other in columns)>1}
    for column in columns:
        if column['field'] in duplicates: column['field'] = None
    # At least two distinct semantic signals, not merely two copies of "Prix".
    signals = {f for c in columns for f in c['candidates']}
    supported = sum(bool(c['candidates']) for c in columns)>=2 and len(signals)>=2
    return columns, supported


def number(value):
    """Unambiguous decimal syntax, optional French space grouping, no currency guessing."""
    if not isinstance(value, str): return None
    value = value.strip().replace('\u00a0', ' ').replace('\u202f', ' ')
    if not re.fullmatch(r'[+-]?(?:\d+|\d{1,3}(?: \d{3})+)(?:[,.]\d+)?', value): return None
    try: return Decimal(value.replace(' ', '').replace(',', '.'))
    except InvalidOperation: return None


def arithmetic(fields):
    names = ('quantity', 'unit_price', 'amount')
    if not all(k in fields for k in names): return None
    values = [number(fields[k]['value']) for k in names]
    if any(v is None for v in values): return {'status':'not_checked', 'reason':'ambiguous_or_missing_numeric_value'}
    # Bound work and decimal context: diagnostic only, never replace source prices.
    if any(len(v.as_tuple().digits)>20 or abs(v.as_tuple().exponent)>10 for v in values):
        return {'status':'not_checked', 'reason':'numeric_precision_limit'}
    from decimal import localcontext
    with localcontext() as context:
        context.prec = 64
        expected = values[0]*values[1]
        difference = values[2]-expected
    return dict(status='mismatch' if abs(difference)>Decimal('0.01') else 'consistent',
                expected_amount=str(expected), difference=str(difference), tolerance='0.01',
                source_values_unchanged=True)
