from backend.speech_text import natural_blocks


def assert_preserved(text):
    blocks = natural_blocks(text)
    assert ' '.join(blocks) == ' '.join(text.split())
    assert all(block and block == block.strip() for block in blocks)
    return blocks


def test_empty_whitespace():
    assert natural_blocks(' \n\t\r\n') == []


def test_medical_sentence_is_not_chopped_for_short_captions():
    text = ('Dr. Jones reviewed the concentration of 1.5 mg/mL with the team, '
            'then asked them to verify the label and local protocol before proceeding.')
    assert natural_blocks(text) == [text]


def test_abbreviations_and_initials_near_target_do_not_split_sentences():
    prefix = 'Review the source carefully and document the required observations. ' * 3
    sentence = 'Dr. A. Jones reviewed 1.5 mg/mL, e.g. the listed concentration, at 10:30 a.m. with staff.'
    blocks = assert_preserved(prefix + sentence)
    assert sentence in blocks
    assert not any(block.endswith(('Dr.', 'A.', 'e.g.', 'a.m.')) for block in blocks)


def test_paragraphs_and_numbered_lists_remain_separate():
    text = 'First paragraph.\n\n1. Verify the source.\n2. Review 0.5 mg/kg.\n\t• Record findings.'
    assert natural_blocks(text) == [
        'First paragraph.', '1. Verify the source.',
        '2. Review 0.5 mg/kg.', '• Record findings.',
    ]


def test_long_sentence_prefers_clause_punctuation():
    clause = 'Review the supplied observations and identify any uncertainty before proceeding'
    text = clause + ', ' + clause + '; ' + clause + ': ' + clause + '.'
    blocks = assert_preserved(text)
    assert len(blocks) > 1
    assert all(len(block) <= 240 for block in blocks)
    assert all(block.endswith((',', ';', ':')) for block in blocks[:-1])


def test_long_unpunctuated_source_preserves_words_and_limit():
    text = ' '.join(['observation'] * 200)
    blocks = assert_preserved(text)
    assert all(len(block) <= 320 for block in blocks)
    assert all(len(block) > 240 for block in blocks[:-1])


def test_decimal_and_unit_are_kept_together_at_word_boundary():
    text = 'x ' * 156 + '1.5 mg/mL ' + 'review ' * 50
    blocks = assert_preserved(text)
    assert any('1.5 mg/mL' in block for block in blocks)
    assert not any(block.endswith('1.5') for block in blocks)
    assert all(len(block) <= 320 for block in blocks)


def test_numbers_negation_ranges_and_quotes_are_unchanged():
    text = 'Do NOT change 1,000 units, 0.5–1.5 mg/kg, or 95%. “Verify this?” Yes!\nDo not infer a dose.'
    assert_preserved(text)


def test_unbroken_token_is_preserved_even_if_long():
    token = 'x' * 400
    assert natural_blocks(token) == [token]


def test_many_sentences_end_at_sentence_boundaries():
    sentence = 'Check the original source before interpreting any ambiguous abbreviation.'
    text = ' '.join([sentence] * 20)
    blocks = assert_preserved(text)
    assert all(block.endswith('.') for block in blocks)
    assert all(len(block) <= 240 for block in blocks)


def test_sentence_ending_with_number_is_a_real_boundary():
    sentence = 'Review the supplied description carefully before referring to the numbered figure 5.'
    blocks = assert_preserved(' '.join([sentence] * 8))
    assert all(block.endswith('5.') for block in blocks)
    assert all(len(block) <= 240 for block in blocks)
