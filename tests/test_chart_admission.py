"""SOURCE ONLY / UNRUN. Invented shape fixtures, no actual provider rows."""
import copy
from datetime import datetime, timezone
import unittest
from chart_admission import assess_chart


DEFAULT_PAYLOAD = object()


class ChartAdmissionTests(unittest.TestCase):
    def payload(self):
        # Entirely invented UTC dates/session/prices, not a market-data snapshot.
        return {'chart': {'error': None, 'result': [{
            'meta': {'symbol': 'EXAMPLE', 'instrumentType': 'EQUITY',
                     'currency': 'USD', 'exchangeTimezoneName': 'UTC',
                     'regularMarketTime': 172800,
                     'currentTradingPeriod': {'regular': {'start': 172800, 'end': 180000}}},
            'timestamp': [86400, 172800],
            'indicators': {'quote': [{'open': [10.0, 11.0], 'high': [10.0, 11.0],
                                      'low': [10.0, 11.0], 'close': [10.0, 11.0],
                                      'volume': [1, 2]}],
                           'adjclose': [{'adjclose': [10.0, 11.0]}]}}]}}

    def assess(self, payload=DEFAULT_PAYLOAD, **kwargs):
        arguments = dict(requested_symbol='EXAMPLE',
                         source_endpoint='https://provider.example/chart/EXAMPLE',
                         retrieved_at=datetime.fromtimestamp(190000, timezone.utc),
                         expected_instrument_type='EQUITY',
                         identity_source_url='https://exchange.example/instrument/EXAMPLE')
        arguments.update(kwargs)
        return assess_chart(self.payload() if payload is DEFAULT_PAYLOAD else payload, **arguments)

    def null_last(self, payload):
        record = payload['chart']['result'][0]
        for values in record['indicators']['quote'][0].values():
            values[-1] = None
        record['indicators']['adjclose'][0]['adjclose'][-1] = None

    def test_closed_missing_bar_not_dropped(self):
        payload = self.payload()
        self.null_last(payload)
        result = self.assess(payload)
        self.assertEqual(result['decision'], 'REFUSE')
        self.assertIn('MISSING_BAR_AFTER_PROVIDER_SESSION_CLOSE', result['reasons'])
        self.assertEqual(result['row_count'], 2)
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(result['rows'][-1]['session_status'], 'CLOSED')
        self.assertNotIn('selected_prices', result)

    def test_open_missing_bar_classified_but_still_refused(self):
        payload = self.payload()
        self.null_last(payload)
        result = self.assess(payload, retrieved_at=datetime.fromtimestamp(175000, timezone.utc))
        self.assertIn('UNFINISHED_CURRENT_BAR_REQUIRES_EXPLICIT_SELECTION', result['reasons'])
        self.assertEqual(result['decision'], 'REFUSE')
        self.assertEqual(result['row_count'], 2)

    def test_valid_current_bar_still_requires_session_close(self):
        result = self.assess(retrieved_at=datetime.fromtimestamp(175000, timezone.utc))
        self.assertEqual(result['decision'], 'REFUSE')
        self.assertIn('CURRENT_SESSION_NOT_CLOSED', result['reasons'])

    def test_exact_session_end_is_closed(self):
        payload = self.payload()
        self.null_last(payload)
        result = self.assess(payload, retrieved_at=datetime.fromtimestamp(180000, timezone.utc))
        self.assertIn('MISSING_BAR_AFTER_PROVIDER_SESSION_CLOSE', result['reasons'])

    def test_window_is_inclusive_start_exclusive_end(self):
        result = self.assess(period_start=86400, period_end=172800)
        self.assertTrue(result['rows'][0]['in_requested_window'])
        self.assertFalse(result['rows'][1]['in_requested_window'])
        self.assertIn('PROVIDER_ROW_OUTSIDE_REQUESTED_WINDOW', result['reasons'])
        self.assertEqual(result['row_count'], 2)

    def test_interior_null_and_partial_null_not_exempt(self):
        for position in (0, 1):
            payload = self.payload()
            payload['chart']['result'][0]['indicators']['quote'][0]['close'][position] = None
            result = self.assess(payload)
            self.assertIn('INVALID_PRICE_ROW', result['reasons'])
            self.assertNotIn('UNFINISHED_CURRENT_BAR_REQUIRES_EXPLICIT_SELECTION', result['reasons'])

    def test_interior_nonfinite_or_nonpositive_refused(self):
        for bad in (float('inf'), float('nan'), 0, -1, True, '10'):
            payload = self.payload()
            payload['chart']['result'][0]['indicators']['quote'][0]['close'][0] = bad
            with self.subTest(bad=bad):
                self.assertIn('INVALID_PRICE_ROW', self.assess(payload)['reasons'])

    def test_type_conflict_and_stale_quote_separate(self):
        payload = self.payload()
        meta = payload['chart']['result'][0]['meta']
        meta['instrumentType'] = 'MUTUALFUND'
        meta['regularMarketTime'] = 1
        result = self.assess(payload)
        self.assertIn('PROVIDER_INSTRUMENT_TYPE_CONFLICT', result['reasons'])
        self.assertIn('QUOTE_TIMESTAMP_MISSING_OR_OLDER_THAN_SERIES', result['reasons'])
        self.assertEqual(result['provider_instrument_type'], 'MUTUALFUND')
        self.assertFalse(result['quote_usable_as_series_current_quote'])

    def test_alias_not_spliced_or_filled(self):
        payload = self.payload()
        record = payload['chart']['result'][0]
        record['meta']['symbol'] = 'OTHER'
        record['meta']['currency'] = None
        record['timestamp'] = record['timestamp'][-1:]
        for values in record['indicators']['quote'][0].values():
            del values[0]
        del record['indicators']['adjclose'][0]['adjclose'][0]
        result = self.assess(payload)
        for reason in ('PROVIDER_SYMBOL_MISMATCH_OR_MISSING', 'CURRENCY_MISSING', 'FEWER_THAN_TWO_DATES'):
            self.assertIn(reason, result['reasons'])
        self.assertEqual(result['provider_symbol'], 'OTHER')
        self.assertIsNone(result['currency'])

    def test_identity_without_external_evidence_unresolved(self):
        result = self.assess(expected_instrument_type=None, identity_source_url=None)
        self.assertIn('EXTERNAL_INSTRUMENT_IDENTITY_UNRESOLVED', result['reasons'])

    def test_duplicate_reversed_and_missing_timestamps_refused(self):
        for timestamps in ([86400, 86400], [172800, 86400], [86400, None]):
            payload = self.payload()
            payload['chart']['result'][0]['timestamp'] = timestamps
            self.assertIn('TIMESTAMPS_INVALID_OR_NOT_UNIQUE_CHRONOLOGICAL', self.assess(payload)['reasons'])

    def test_bad_session_no_unclosed_assumption(self):
        payload = self.payload()
        self.null_last(payload)
        del payload['chart']['result'][0]['meta']['currentTradingPeriod']
        result = self.assess(payload)
        self.assertIn('PROVIDER_SESSION_EVIDENCE_MISSING', result['reasons'])
        self.assertIn('INVALID_PRICE_ROW', result['reasons'])

    def test_malformed_arrays_and_provider_error_refused(self):
        payload = self.payload()
        payload['chart']['result'][0]['indicators']['quote'][0]['close'] = []
        self.assertIn('RESPONSE_SCHEMA_INVALID', self.assess(payload)['reasons'])
        payload = self.payload()
        payload['chart']['error'] = {'code': 'Not Found'}
        self.assertIn('PROVIDER_ERROR', self.assess(payload)['reasons'])

    def test_input_not_mutated_and_provenance_distinct(self):
        payload = self.payload()
        before = copy.deepcopy(payload)
        result = self.assess(payload)
        self.assertEqual(payload, before)
        self.assertEqual(result['requested_symbol'], 'EXAMPLE')
        self.assertEqual(result['provider_symbol'], 'EXAMPLE')
        self.assertEqual(result['series_asof'], '1970-01-03')
        self.assertEqual(result['source_endpoint'], 'https://provider.example/chart/EXAMPLE')
        self.assertEqual(result['decision'], 'STRUCTURAL_CHECKS_CLEAR_NOT_FINANCIAL_QUALIFICATION')
        self.assertEqual(result['adjustment_status'], 'PROVIDER_ADJCLOSE_PRESENT_NOT_INDEPENDENTLY_QUALIFIED')

    def test_missing_aware_time_or_invalid_window_refused(self):
        self.assertIn('RETRIEVAL_TIME_NOT_AWARE', self.assess(retrieved_at=datetime(1970, 1, 4))['reasons'])
        for start, end in ((1, None), (2, 1), ('1', 2)):
            self.assertIn('REQUEST_WINDOW_INVALID', self.assess(period_start=start, period_end=end)['reasons'])


    def field_array(self, payload, field):
        indicators = payload['chart']['result'][0]['indicators']
        return (indicators['adjclose'][0]['adjclose'] if field == 'adjclose'
                else indicators['quote'][0][field])

    def test_all_price_fields_strict_interior_and_last_matrix(self):
        for field in ('open', 'high', 'low', 'close', 'adjclose'):
            for position in (0, 1):
                for bad in (None, float('nan'), float('inf'), -float('inf'),
                            0, -1, True, False, '10', {}, []):
                    with self.subTest(field=field, position=position, bad=bad):
                        payload = self.payload()
                        self.field_array(payload, field)[position] = bad
                        result = self.assess(payload)
                        self.assertEqual(result['decision'], 'REFUSE')
                        self.assertIn('INVALID_PRICE_ROW', result['reasons'])
                        self.assertIn(field, result['rows'][position]['invalid_fields'])
                        self.assertEqual(len(result['rows']), 2)
                        self.assertIn(field, result['rows'][position]['values'])

    def test_volume_strict_interior_and_last_matrix(self):
        for position in (0, 1):
            for bad in (None, float('nan'), float('inf'), -float('inf'),
                        -1, True, False, '2', {}, []):
                with self.subTest(position=position, bad=bad):
                    payload = self.payload()
                    self.field_array(payload, 'volume')[position] = bad
                    result = self.assess(payload)
                    self.assertEqual(result['decision'], 'REFUSE')
                    self.assertIn('volume', result['rows'][position]['invalid_fields'])
                    self.assertEqual(result['row_count'], 2)

    def test_zero_and_fractional_volume_are_not_repaired(self):
        for value in (0, 0.5):
            payload = self.payload()
            self.field_array(payload, 'volume')[:] = [value, value]
            result = self.assess(payload)
            self.assertEqual(result['decision'], 'STRUCTURAL_CHECKS_CLEAR_NOT_FINANCIAL_QUALIFICATION')
            self.assertEqual(result['rows'][0]['values']['volume'], value)
            self.assertEqual(result['rows'][0]['invalid_fields'], [])

    def test_invalid_timezone_keeps_raw_rows_and_independent_failures(self):
        for bad_zone in (None, 'Unlisted/Zone', '', 1, '/UTC'):
            payload = self.payload()
            payload['chart']['result'][0]['meta']['exchangeTimezoneName'] = bad_zone
            self.field_array(payload, 'open')[0] = None
            result = self.assess(payload, period_start=86400, period_end=172800)
            self.assertIn('TIMEZONE_INVALID', result['reasons'])
            self.assertIn('INVALID_PRICE_ROW', result['reasons'])
            self.assertIn('PROVIDER_ROW_OUTSIDE_REQUESTED_WINDOW', result['reasons'])
            self.assertEqual(result['row_count'], len(result['rows']))
            self.assertEqual(result['rows'][1]['timestamp'], 172800)
            self.assertIsNone(result['rows'][0]['date'])
            self.assertEqual(result['rows'][0]['session_status'], 'UNKNOWN')
            self.assertIsNone(result['series_asof'])

    def test_invalid_timestamp_inventory_matrix(self):
        for bad in (None, True, '172800', float('nan'), float('inf'), 10 ** 1000):
            payload = self.payload()
            payload['chart']['result'][0]['timestamp'][1] = bad
            result = self.assess(payload)
            self.assertIn('TIMESTAMPS_INVALID_OR_NOT_UNIQUE_CHRONOLOGICAL', result['reasons'])
            self.assertEqual(result['row_count'], 2)
            self.assertEqual(len(result['rows']), 2)
            self.assertTrue(result['rows'][1]['timestamp_available'])
            self.assertIsNone(result['rows'][1]['date'])
            self.assertIn('close', result['rows'][1]['values'])
            self.assertIsNone(result['series_asof'])

    def test_out_of_range_timestamp_keeps_evidence(self):
        payload = self.payload()
        payload['chart']['result'][0]['timestamp'][1] = 1e100
        result = self.assess(payload)
        self.assertIn('TIMESTAMPS_OUT_OF_RANGE', result['reasons'])
        self.assertEqual(result['rows'][1]['timestamp'], 1e100)
        self.assertEqual(result['row_count'], len(result['rows']))
        self.assertIsNone(result['series_asof'])

    def test_duplicate_and_reversed_inventory_not_erased(self):
        for values in ([86400, 86400], [172800, 86400]):
            payload = self.payload()
            payload['chart']['result'][0]['timestamp'] = values
            result = self.assess(payload)
            self.assertIn('TIMESTAMPS_INVALID_OR_NOT_UNIQUE_CHRONOLOGICAL', result['reasons'])
            self.assertEqual([row['timestamp'] for row in result['rows']], values)
            self.assertEqual(result['row_count'], 2)
            self.assertIsNone(result['series_asof'])

    def test_each_missing_field_array_and_index_is_partial_not_null_fill(self):
        for field in ('open', 'high', 'low', 'close', 'volume', 'adjclose'):
            for position in (0, 1):
                payload = self.payload()
                del self.field_array(payload, field)[position:]
                result = self.assess(payload)
                self.assertEqual(result['inventory_status'], 'PARTIAL')
                self.assertIn('RESPONSE_SCHEMA_INVALID', result['reasons'])
                self.assertEqual(result['row_count'], 2)
                self.assertEqual(len(result['rows']), 2)
                self.assertIn(field, result['rows'][position]['unavailable_fields'])
                self.assertNotIn(field, result['rows'][position]['values'])
                self.assertNotIn(field, result['rows'][position]['missing_fields'])
                self.assertIsNone(result['series_asof'])

    def test_extra_array_slots_kept_without_timestamp_invention(self):
        payload = self.payload()
        self.field_array(payload, 'volume').append(3)
        result = self.assess(payload)
        self.assertEqual(result['row_count'], 3)
        self.assertEqual(result['timestamp_count'], 2)
        self.assertEqual(result['inventory_status'], 'PARTIAL')
        self.assertFalse(result['rows'][2]['timestamp_available'])
        self.assertIsNone(result['rows'][2]['timestamp'])
        self.assertIsNone(result['rows'][2]['date'])
        self.assertEqual(result['rows'][2]['values'], {'volume': 3})

    def test_missing_timestamp_array_keeps_available_fields(self):
        payload = self.payload()
        del payload['chart']['result'][0]['timestamp']
        result = self.assess(payload)
        self.assertEqual(result['inventory_status'], 'PARTIAL')
        self.assertEqual(result['row_count'], 2)
        self.assertIsNone(result['timestamp_count'])
        self.assertFalse(result['rows'][0]['timestamp_available'])
        self.assertEqual(result['rows'][0]['values']['close'], 10.0)
        self.assertIn('RESPONSE_SCHEMA_INVALID', result['reasons'])

    def test_missing_groups_and_bad_singleton_types_do_not_index_or_discard(self):
        for key in ('quote', 'adjclose'):
            for bad in (None, [], [None], {}, [[], []]):
                payload = self.payload()
                payload['chart']['result'][0]['indicators'][key] = bad
                result = self.assess(payload)
                self.assertEqual(result['decision'], 'REFUSE')
                self.assertEqual(result['inventory_status'], 'PARTIAL')
                self.assertEqual(result['row_count'], 2)
                self.assertEqual(len(result['rows']), 2)
                self.assertIn('RESPONSE_SCHEMA_INVALID', result['reasons'])

    def test_unusable_schema_inventory_explicitly_unavailable(self):
        for payload in (None, [], {}, {'chart': None},
                        {'chart': {'result': []}}, {'chart': {'result': [None]}},
                        {'chart': {'result': [{}, {}]}}):
            result = self.assess(payload)
            self.assertEqual(result['decision'], 'REFUSE')
            self.assertEqual(result['inventory_status'], 'UNAVAILABLE')
            self.assertTrue(result['inventory_issues'])
            self.assertEqual(result['rows'], [])
            self.assertEqual(result['row_count'], 0)

    def test_invalid_metadata_and_receipt_do_not_hide_inventory(self):
        for bad in (None, [], 'metadata'):
            payload = self.payload()
            payload['chart']['result'][0]['meta'] = bad
            result = self.assess(payload, retrieved_at=datetime(1970, 1, 4))
            self.assertIn('RETRIEVAL_TIME_NOT_AWARE', result['reasons'])
            self.assertIn('TIMEZONE_INVALID', result['reasons'])
            self.assertEqual(result['row_count'], 2)
            self.assertEqual(result['rows'][0]['values']['close'], 10.0)

    def test_provider_error_keeps_available_result_inventory(self):
        payload = self.payload()
        payload['chart']['error'] = {'code': 'ExampleError'}
        result = self.assess(payload)
        self.assertIn('PROVIDER_ERROR', result['reasons'])
        self.assertEqual(result['row_count'], 2)
        self.assertEqual(result['rows'][1]['timestamp'], 172800)

    def test_every_nonarray_or_absent_field_preserves_other_evidence(self):
        for field in ('open', 'high', 'low', 'close', 'volume', 'adjclose'):
            for bad in (None, '10', 1, {}, True):
                payload = self.payload()
                indicators = payload['chart']['result'][0]['indicators']
                group = indicators['adjclose'][0] if field == 'adjclose' else indicators['quote'][0]
                group[field] = bad
                result = self.assess(payload)
                self.assertEqual(result['inventory_status'], 'PARTIAL')
                self.assertEqual(result['row_count'], 2)
                self.assertIn(field, result['rows'][0]['unavailable_fields'])
                self.assertIn('RESPONSE_SCHEMA_INVALID', result['reasons'])
            payload = self.payload()
            indicators = payload['chart']['result'][0]['indicators']
            group = indicators['adjclose'][0] if field == 'adjclose' else indicators['quote'][0]
            del group[field]
            result = self.assess(payload)
            self.assertIn(field, result['rows'][1]['unavailable_fields'])
            self.assertEqual(result['inventory_status'], 'PARTIAL')

    def test_interior_all_null_is_not_given_final_session_exception(self):
        payload = self.payload()
        for field in ('open', 'high', 'low', 'close', 'volume', 'adjclose'):
            self.field_array(payload, field)[0] = None
        result = self.assess(payload)
        self.assertIn('INVALID_PRICE_ROW', result['reasons'])
        self.assertNotIn('MISSING_BAR_AFTER_PROVIDER_SESSION_CLOSE', result['reasons'])
        self.assertNotIn('UNFINISHED_CURRENT_BAR_REQUIRES_EXPLICIT_SELECTION', result['reasons'])
        self.assertEqual(len(result['rows'][0]['missing_fields']), 6)
        self.assertEqual(len(result['rows'][0]['invalid_fields']), 6)

    def test_date_resolution_status_never_invented(self):
        payload = self.payload()
        payload['chart']['result'][0]['timestamp'][1] = None
        result = self.assess(payload)
        self.assertEqual(result['rows'][0]['date_status'], 'RESOLVED')
        self.assertEqual(result['rows'][1]['date_status'], 'TIMESTAMP_INVALID')
        payload = self.payload()
        del payload['chart']['result'][0]['meta']['exchangeTimezoneName']
        result = self.assess(payload)
        self.assertEqual(result['rows'][0]['date_status'], 'TIMEZONE_UNRESOLVED')
        payload = self.payload()
        payload['chart']['result'][0]['timestamp'][1] = 1e100
        result = self.assess(payload)
        self.assertEqual(result['rows'][1]['date_status'], 'TIMESTAMP_OUT_OF_RANGE')

    def test_missing_indicators_retains_timestamp_only_partial_inventory(self):
        payload = self.payload()
        del payload['chart']['result'][0]['indicators']
        result = self.assess(payload)
        self.assertEqual(result['inventory_status'], 'PARTIAL')
        self.assertEqual(result['row_count'], 2)
        self.assertEqual(result['rows'][0]['values'], {})
        self.assertEqual(len(result['rows'][0]['unavailable_fields']), 6)
        self.assertEqual(result['rows'][0]['timestamp'], 86400)


if __name__ == '__main__':
    unittest.main()
