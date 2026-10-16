import copy
from datetime import datetime, timedelta
import tempfile
import unittest
from pathlib import Path

import track


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 12, tzinfo=track.TZ)
        self.sources = {'rules': {'status': 'ok', 'kind': 'document'},
                        'sale': {'status': 'ok', 'kind': 'merchant'}}
        self.offer = {'id': 'hotel-A', 'title': 'Test hotel', 'source_id': 'rules',
                      'url': 'https://example.com/hotel-A',
                      'booking_start': '2026-10-01', 'booking_end': '2026-10-31',
                      'booking_year_verified': True, 'availability': 'unknown'}

    def status(self, **updates):
        return track.classify({**self.offer, **updates}, self.sources, self.now)[0]

    def test_stay_deadline_does_not_extend_booking(self):
        self.assertEqual(self.status(booking_end='2026-10-14', stay_raw='入住到11月7日'), 'expired')

    def test_missing_year_does_not_become_this_year(self):
        self.assertEqual(self.status(booking_year_verified=False), 'needs_verification')

    def test_unknown_purchase_window_not_inferred_from_redemption(self):
        self.assertEqual(self.status(booking_start=None, booking_end=None,
                                     redemption_raw='11月30日前核销'), 'needs_verification')

    def test_open_terms_without_inventory_only_candidate(self):
        self.assertEqual(self.status(), 'open_by_terms')

    def test_search_snippet_is_not_terms_verification(self):
        self.sources['rules']['kind'] = 'search'
        self.assertEqual(self.status(), 'needs_verification')

    def test_confirmation_requires_merchant_match_cash_and_no_gaps(self):
        verified = dict(availability='available', merchant_source_id='sale', itinerary_match=True,
                        eligibility='matched', terms_checked=True, price={'cash': 282}, missing=[])
        self.assertEqual(self.status(**verified), 'confirmed_bookable')
        for override in [{'merchant_source_id': 'rules'}, {'missing': ['税费']},
                         {'price': {'points': 3034}}, {'itinerary_match': False},
                         {'eligibility': 'unknown'}]:
            self.assertEqual(self.status(**{**verified, **override}), 'open_by_terms')

    def test_conflicting_rules_block_confirmation(self):
        self.assertEqual(self.status(conflict=True), 'needs_verification')

    def test_precise_deadline_and_cross_year(self):
        self.assertEqual(self.status(booking_end='2026-10-16T11:59:00+08:00'), 'expired')
        self.assertEqual(self.status(booking_end='2026-10-16'), 'open_by_terms')
        self.assertEqual(self.status(booking_start='2026-12-01', booking_end='2027-01-18'), 'not_started')

    def test_unavailable_requires_sales_evidence(self):
        self.assertEqual(self.status(availability='unavailable'), 'needs_verification')
        self.assertEqual(self.status(availability='unavailable', merchant_source_id='sale'), 'unavailable')

    def test_partial_run_preserves_missing_old_offer(self):
        prior = {'run_id': 'old', 'offers': [self.offer]}
        diff, missing = track.changes(prior, [], 'new')
        self.assertEqual(diff['not_rechecked'], ['hotel-A'])
        self.assertEqual(missing[0]['last_observed_run_id'], 'old')
        _, missing_again = track.changes({'run_id': 'new', 'not_rechecked': missing}, [], 'newer')
        self.assertEqual(missing_again[0]['last_observed_run_id'], 'old')

    def test_content_change_not_fetch_time_drives_diff(self):
        prior = {'offers': [{**self.offer, 'fetched_at': 'old'}]}
        diff, _ = track.changes(prior, [{**self.offer, 'fetched_at': 'new'}], 'new')
        self.assertEqual(diff['unchanged'], ['hotel-A'])
        diff, _ = track.changes(prior, [{**self.offer, 'price': {'cash': 999}}], 'new')
        self.assertEqual(diff['changed'], ['hotel-A'])

    def test_evidence_time_path_and_blocked_source_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / 'evidence').mkdir()
            (run / 'evidence/page.txt').write_text('test fixture')
            context = {'run_id': 'test', 'started_at': (self.now - timedelta(minutes=5)).isoformat()}
            data = {'run_id': 'test', 'coverage': 'partial', 'coverage_note': 'fixture only',
                    'sources': [{'id': 'rules', 'kind': 'document', 'status': 'ok',
                                 'url': 'https://example.com', 'fetched_at': self.now.isoformat(),
                                 'evidence': ['evidence/page.txt']}], 'offers': [self.offer]}
            track.validate(copy.deepcopy(data), context, run, self.now)
            for change in [{'fetched_at': (self.now - timedelta(days=1)).isoformat()},
                           {'fetched_at': (self.now + timedelta(minutes=1)).isoformat()},
                           {'evidence': ['../outside.txt']}, {'evidence': []}]:
                invalid = copy.deepcopy(data)
                invalid['sources'][0].update(change)
                with self.assertRaises(ValueError):
                    track.validate(invalid, context, run, self.now)
            invalid = copy.deepcopy(data)
            invalid['sources'][0].update(status='blocked', note='login needed')
            invalid['coverage'] = 'complete'
            with self.assertRaises(ValueError):
                track.validate(invalid, context, run, self.now)

    def test_start_finish_and_stale_concurrent_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = track.start(tmp)
            second = track.start(tmp)
            for context in (first, second):
                run = Path(context['run_dir'])
                data = track.read(run / 'observations.json')
                data['coverage_note'] = 'No sources available in this isolated test'
                track.write(run / 'observations.json', data)
            r = Path(first['run_dir'])
            track.finish(r, r / 'observations.json')
            self.assertTrue((r / 'report.md').exists())
            s = Path(second['run_dir'])
            with self.assertRaises(ValueError):
                track.finish(s, s / 'observations.json')
            self.assertEqual(track.read(Path(tmp) / 'latest.json')['run_id'], first['run_id'])


if __name__ == '__main__':
    unittest.main()
