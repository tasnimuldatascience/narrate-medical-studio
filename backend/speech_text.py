"""Conservative, content-preserving boundaries for offline speech synthesis.

Sentence and clause boundaries keep a voice's prosody intact. Whitespace is
normalized, but spelling, punctuation, quantities, and units are never rewritten.
"""
import re

_TARGET = 240
_MAXIMUM = 320
_ABBREVIATIONS = {
    'dr', 'mr', 'mrs', 'ms', 'prof', 'sr', 'jr', 'st', 'vs', 'fig', 'figs',
    'no', 'nos', 'vol', 'pp', 'approx', 'dept', 'ref', 'refs', 'inc', 'ltd',
    'e.g', 'i.e', 'et al', 'a.m', 'p.m', 'b.i.d', 't.i.d', 'q.i.d', 'p.r.n',
}
_SENTENCE_END = re.compile(r'[.!?]+["\u201d\u2019\')\]]*(?=\s|$)')
_NUMBER = re.compile(r'^[<>\u2264\u2265~]?[+-]?\d+(?:[.,]\d+)*(?:[-\u2013]\d+(?:\.\d+)?)?$')
_UNIT = re.compile(
    r'^(?:mcg|\u00b5g|\u03bcg|mg|g|kg|ng|mL|ml|L|l|dL|dl|mmol|mol|mEq|'
    r'IU|U|units?|mmHg|cm|mm|m|bpm|Hz|kHz|%|\u00b0C|\u00b0F)'
    r'(?:/(?:kg|mL|ml|L|l|dL|dl|min|h|hr|day|s))*[.,;:!?)]?$', re.I,
)


def _sentences(line):
    start = 0
    for match in _SENTENCE_END.finditer(line):
        end = match.end()
        punctuation = match.group().rstrip('"\u201d\u2019\')]').rstrip()
        if punctuation == '.':
            prefix = line[:match.start()]
            token = prefix.rsplit(' ', 1)[-1]
            # Titles, medical abbreviations, initials, decimal dots, and dotted
            # acronyms are not safe places to reset the voice.
            if (token.lower() in _ABBREVIATIONS
                    or prefix.lower().endswith('et al')
                    or re.fullmatch(r'(?:[A-Za-z]\.)*[A-Za-z]', token)
                    or re.fullmatch(r'\d+', prefix) and start == 0):
                continue
        yield line[start:end].strip()
        start = end
    if line[start:].strip():
        yield line[start:].strip()


def _word_parts(text):
    """Fall back at words, keeping a quantity beside its recognized unit.

    A single unbroken token or quantity/unit pair longer than the limit is kept
    intact: source integrity takes precedence over an artificial character cap.
    """
    words = text.split()
    atoms = []
    for word in words:
        if atoms and _NUMBER.fullmatch(atoms[-1]) and _UNIT.fullmatch(word):
            atoms[-1] += ' ' + word
        else:
            atoms.append(word)
    current = ''
    for atom in atoms:
        candidate = f'{current} {atom}' if current else atom
        if current and len(candidate) > _MAXIMUM:
            yield current
            current = atom
        else:
            current = candidate
    if current:
        yield current


def _long_sentence(sentence):
    if len(sentence) <= _TARGET:
        yield sentence
        return
    # Require following whitespace so ratios, decimals, times, and thousands
    # separators inside tokens are not treated as clause boundaries.
    clauses = re.split(r'(?<=[,;:])\s+|(?<=\u2014)\s+', sentence)
    current = ''
    for clause in clauses:
        candidate = f'{current} {clause}' if current else clause
        if current and len(candidate) > _TARGET:
            yield from _word_parts(current)
            current = clause
        else:
            current = candidate
    if current:
        yield from _word_parts(current)


def natural_blocks(text: str) -> list[str]:
    """Return natural speech/caption blocks without changing source content.

    Newlines preserve paragraph and list boundaries. Short adjacent sentences
    share a block up to 240 characters. Long sentences split at clauses, then
    words at 320 characters where necessary. Joining the result with a space
    reproduces the input with whitespace normalized.
    """
    result = []
    for raw_line in text.splitlines():
        line = ' '.join(raw_line.split())
        if not line:
            continue
        current = ''
        for sentence in _sentences(line):
            for part in _long_sentence(sentence):
                candidate = f'{current} {part}' if current else part
                if current and len(candidate) > _TARGET:
                    result.append(current)
                    current = part
                else:
                    current = candidate
        if current:
            result.append(current)
    return result
