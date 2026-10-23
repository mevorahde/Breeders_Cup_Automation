import json
from pathlib import Path
import unittest
from breeders_cup.schedule import parse_schedule,schedule_links


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).parent/'fixtures'
        self.html=(root/'race-order.html').read_text(encoding='utf8')
        fixture=json.loads((root/'official.json').read_text())
        from breeders_cup.collector import parse_official
        self.data=parse_official('<script id="__NEXT_DATA__">'+json.dumps(fixture)+'</script>',2026,'2026-10-23')

    def test_all_fourteen_numbers_and_eastern_post_times(self):
        found,_=parse_schedule(self.html,self.data['races'],2026)
        keyed={r['name']:found[r['id']] for r in self.data['races']}
        self.assertEqual(len(found),14)
        self.assertEqual(keyed['Juvenile Turf Sprint']['number'],6)
        self.assertEqual(keyed['Juvenile Turf Sprint']['scheduled_at'],'2026-10-30T18:55:00+00:00')
        self.assertEqual(keyed['Filly & Mare Sprint']['number'],4)
        self.assertEqual(keyed['Classic']['number'],12)
        self.assertEqual(keyed['Classic']['post_time_et'],'6:16 PM')

    def test_wrong_year_and_duplicate_schedule_are_rejected(self):
        with self.assertRaises(ValueError):parse_schedule(self.html,self.data['races'],2027)
        bad=self.html.replace('Race 7','Race 6')
        with self.assertRaisesRegex(ValueError,'Duplicate'):parse_schedule(bad,self.data['races'],2026)

    def test_discovery_only_uses_official_current_year_article(self):
        url='/news/2026/final-2026-breeders-cup-race-order-post-times-wagering-menu-Announced'
        html=f'<a href="{url}">Official schedule</a><a href="https://example.com{url}">Other</a>'
        self.assertEqual(schedule_links(html,2026),{'https://www.breederscup.com'+url})
        self.assertEqual(schedule_links(html,2025),set())
