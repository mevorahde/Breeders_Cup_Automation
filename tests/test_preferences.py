import unittest
from breeders_cup.core import famous_ancestors, post_order


class PreferenceTests(unittest.TestCase):
    def test_famous_punctuation_country_and_duplicates(self):
        horse={'pedigree_ancestors':['AP Indy (USA)','MR PROSPECTOR','Secretariat Junior']}
        self.assertEqual(famous_ancestors(horse,['A.P. Indy','AP Indy','Mr. Prospector','Mr Prospector','Secretariat']),
                         'A.P. Indy; Mr. Prospector')

    def test_famous_matches_verified_names_once(self):
        horse = {'father': 'Secretariat', 'grandfathers': 'Other; SECRETARIAT',
                 'pedigree_ancestors': [' Seattle   Slew ', 'Secretariat', 'Unlisted']}
        self.assertEqual(famous_ancestors(horse, ['Secretariat', 'Seattle Slew', 'Famous']),
                         'Seattle Slew; Secretariat')

    def test_no_substrings_or_unverified_input(self):
        self.assertEqual(famous_ancestors({'pedigree_ancestors': ['Secretariat Junior'],
                                         'other_ancestors': 'Secretariat'}, ['Secretariat']), '')
        self.assertEqual(famous_ancestors({'father': 'Secretariat'}, []), '')
        with self.assertRaises(ValueError):
            famous_ancestors({'pedigree_ancestors': 'Secretariat'}, ['Secretariat'])

    def test_posts_sort_numerically_and_unassigned_alphabetically(self):
        horse = {'name': 'Alpha'}
        values = ['10', None, 'SCR', '2', 'AE', 1]
        ordered = sorted(values, key=lambda p: post_order({'post': p, 'horse_id': 'a'}, horse))
        self.assertEqual(ordered, [1, '2', '10', 'AE', 'SCR', None])
        self.assertLess(post_order({'horse_id': 'b'}, {'name': 'Alpha'}),
                        post_order({'horse_id': 'a'}, {'name': 'Beta'}))

    def test_invalid_post_is_not_silently_sorted(self):
        with self.assertRaises(ValueError):
            post_order({'post': 'TBD?', 'horse_id': 'a'}, {'name': 'Alpha'})
