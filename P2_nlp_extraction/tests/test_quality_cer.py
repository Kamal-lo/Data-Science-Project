import unittest

from P2_nlp_extraction.quality_evaluation import character_errors, word_errors


class DistanceTests(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(character_errors('Texte عربي','Texte عربي')['cer'],0)

    def test_substitution(self):
        r=character_errors('abc','axc');self.assertEqual((r['substitutions'],r['insertions'],r['deletions']),(1,0,0))

    def test_insertion(self):
        r=character_errors('abc','abxc');self.assertEqual((r['substitutions'],r['insertions'],r['deletions']),(0,1,0))

    def test_deletion(self):
        r=character_errors('abcd','acd');self.assertEqual((r['substitutions'],r['insertions'],r['deletions']),(0,0,1))

    def test_spaces_accents_newlines_not_removed(self):
        self.assertEqual(character_errors('é a','e  a')['total_errors'],2)
        self.assertEqual(character_errors('a\r\n','a\n')['deletions'],1)

    def test_unicode_nfc_only_if_explicit(self):
        self.assertGreater(character_errors('é','e\u0301')['cer'],0)
        self.assertEqual(character_errors('é','e\u0301',normalization='NFC')['cer'],0)

    def test_arabic_marks_tatweel_and_letters_preserved(self):
        for left,right in (('أ','ا'),('ي','ى'),('عَقد','عقد'),('عـقد','عقد')):
            with self.subTest(left=left):self.assertGreater(character_errors(left,right)['total_errors'],0)

    def test_empty_reference_undefined_and_empty_prediction_deletions(self):
        self.assertIsNone(character_errors('','abc'))
        self.assertEqual(character_errors('abc','')['deletions'],3)

    def test_cer_can_exceed_one_hundred_percent(self):
        self.assertEqual(character_errors('a','aaaa')['cer_percent'],300)

    def test_known_distance_and_counts_identity(self):
        r=character_errors('kitten','sitting')
        self.assertEqual(r['total_errors'],3)
        self.assertEqual(r['substitutions']+r['insertions']+r['deletions'],3)

    def test_budget_and_invalid_options(self):
        with self.assertRaises(ValueError):character_errors('abc','abc',max_alignment_cells=2)
        with self.assertRaises(ValueError):character_errors('a','a',normalization='strip')

    def test_word_errors_keep_diacritics_and_split_on_whitespace(self):
        result = word_errors('École\tعَقد', 'École\nعقد زائد')
        self.assertEqual(result['reference_words'], 2)
        self.assertEqual((result['substitutions'], result['insertions']), (1, 1))
        self.assertEqual(result['wer'], 1)
        self.assertIsNone(word_errors(' \n', 'Texte'))
