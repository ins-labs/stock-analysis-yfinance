"""Invented EGX-shape fixtures only. SOURCE / UNRUN; no actual market rows."""
import copy
import hashlib
import json
import unittest
from egx_close_volume_admission import assess_egx_close_volume


DEFAULT = object()


class EgxCloseVolumeTests(unittest.TestCase):
    def series(self):
        return {'success': True, 'totalCount': 2, 'data': [
            {'isinCode': 'INVENTED001', 'name': 'Example Equity',
             'tradeDate': '2020-02-02T00:00:00', 'closePrice': 12.0, 'tradeVolume': 0},
            {'isinCode': 'INVENTED001', 'name': 'Example Equity',
             'tradeDate': '2020-02-03T00:00:00', 'closePrice': 13.0, 'tradeVolume': 1.5}]}

    def reference(self):
        return {'success': True, 'totalCount': 1, 'data': [{
            'isin': 'INVENTED001', 'reuters': 'EXAMPLE.CA', 'name': 'Example Equity',
            'schedule': 'Egyptian securities-Stocks', 'curr': 'L.E',
            'curR_LONG': 'Egyptian Pound', 'lasT_TRADE_DATE': '2020-02-02T00:00:00',
            'lasT_CP': 12.0}]}

    def encode(self, value):
        return json.dumps(value).encode()

    def receipt(self, raw, path, query):
        url = 'https://beta.egx.com.eg/api/bff/egx/' + path + '?' + query
        return {'url': url, 'final_url': url, 'status': 200,
                'retrieved_utc': '2020-02-04T18:00:00+00:00',
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

    def assess(self, series=DEFAULT, reference=DEFAULT, *, receipt_patch=None,
               reference_receipt_patch=None, raw_series=None, raw_reference=None, **changes):
        series = self.series() if series is DEFAULT else series
        reference = self.reference() if reference is DEFAULT else reference
        sb = self.encode(series) if raw_series is None else raw_series
        rb = self.encode(reference) if raw_reference is None else raw_reference
        sr = self.receipt(sb, 'price-volume-points', 'isin=INVENTED001&date=30')
        rr = self.receipt(rb, 'stock-info', 'Isin=INVENTED001')
        sr.update(receipt_patch or {})
        rr.update(reference_receipt_patch or {})
        args = dict(series_receipt=sr, reference_receipt=rr,
                    requested_isin='INVENTED001', requested_symbol='EXAMPLE.CA', requested_days=30,
                    window_start='2020-02-02', window_end='2020-02-03', expected_asof='2020-02-03',
                    admissible_since='2020-02-01', policy_source_url='https://evidence.example/post-action')
        args.update(changes)
        return assess_egx_close_volume(sb, rb, **args)

    def test_valid_full_response_reference_join_and_scope(self):
        result = self.assess()
        self.assertEqual(result['decision'], 'STRUCTURAL_CLOSE_VOLUME_CLEAR_NOT_FINANCIAL_QUALIFICATION')
        self.assertEqual(result['row_count'], 2)
        self.assertEqual(result['inventory_status'], 'COMPLETE')
        self.assertEqual(result['currency'], 'EGP')
        self.assertEqual(result['currency_provenance']['source'], 'OWNING_STOCK_INFO_REFERENCE')
        self.assertEqual(result['series_asof'], '2020-02-03')
        self.assertEqual(result['reference_asof'], '2020-02-02T00:00:00')
        self.assertFalse(result['current_quote_usable'])
        self.assertNotIn('selected_prices', result)
        self.assertNotIn('adjusted_close', result)
        self.assertNotIn('open', result['rows'][0]['raw'])
        self.assertEqual(result['rows'][0]['raw']['closePrice'], 12.0)
        self.assertNotEqual(result['rows'][-1]['raw']['closePrice'], 12.0)

    def test_numeric_fields_interior_and_last_matrix(self):
        for field in ('closePrice', 'tradeVolume'):
            for position in (0, 1):
                bad_values = [None, True, False, '12', float('nan'), float('inf'),
                              -float('inf'), -1, {}, [], 10 ** 1000]
                if field == 'closePrice':
                    bad_values.append(0)
                for bad in bad_values:
                    with self.subTest(field=field, position=position, bad=bad):
                        series = self.series()
                        series['data'][position][field] = bad
                        result = self.assess(series)
                        self.assertEqual(result['decision'], 'REFUSE')
                        self.assertIn('SERIES_NUMERIC_FIELD_INVALID', result['reasons'])
                        self.assertIn(field, result['rows'][position]['invalid_fields'])
                        self.assertEqual(len(result['rows']), 2)

    def test_zero_and_fractional_volume_retained(self):
        result = self.assess()
        self.assertEqual(result['rows'][0]['raw']['tradeVolume'], 0)
        self.assertEqual(result['rows'][1]['raw']['tradeVolume'], 1.5)
        self.assertEqual(result['reasons'], [])

    def test_owning_reference_identity_type_matrix(self):
        for field, bad in [('isin', 'OTHER'), ('reuters', 'ALIAS'), ('name', ''),
                           ('schedule', 'Funds'), ('schedule', None)]:
            reference = self.reference()
            reference['data'][0][field] = bad
            result = self.assess(reference=reference)
            self.assertIn('REFERENCE_IDENTITY_OR_EQUITY_CONFLICT', result['reasons'])
            self.assertEqual(result['row_count'], 2)

    def test_currency_missing_and_conflicting_not_defaulted(self):
        for field, bad in [('curr', None), ('curr', 'USD'), ('curR_LONG', None),
                           ('curR_LONG', 'US Dollar')]:
            reference = self.reference()
            reference['data'][0][field] = bad
            result = self.assess(reference=reference)
            self.assertIn('REFERENCE_CURRENCY_UNRESOLVED', result['reasons'])
            self.assertIsNone(result['currency'])
            self.assertIsNone(result['currency_provenance'])

    def test_each_row_identity_conflict_no_alias_join(self):
        for position in (0, 1):
            for field in ('isinCode', 'name'):
                series = self.series()
                series['data'][position][field] = 'OTHER'
                result = self.assess(series)
                self.assertIn('SERIES_REFERENCE_IDENTITY_CONFLICT', result['reasons'])
                self.assertEqual(result['row_count'], 2)

    def test_missing_row_fields_preserve_available_inventory(self):
        for field in ('isinCode', 'name', 'tradeDate', 'closePrice', 'tradeVolume'):
            for position in (0, 1):
                series = self.series()
                del series['data'][position][field]
                result = self.assess(series)
                self.assertIn('SERIES_ROW_SCHEMA_INVALID', result['reasons'])
                self.assertEqual(result['inventory_status'], 'PARTIAL')
                self.assertIn(field, result['rows'][position]['missing_fields'])
                self.assertEqual(len(result['rows']), 2)

    def test_malformed_row_preserves_full_positions(self):
        series = self.series()
        series['data'][0] = None
        result = self.assess(series)
        self.assertEqual(result['row_count'], 2)
        self.assertIsNone(result['rows'][0]['raw'])
        self.assertEqual(result['inventory_status'], 'PARTIAL')
        self.assertIn('SERIES_ROW_SCHEMA_INVALID', result['reasons'])
        self.assertIsNone(result['series_asof'])

    def test_date_format_and_calendar_matrix(self):
        for position in (0, 1):
            for bad in (None, 1, '2020-02-30T00:00:00', '2020-02-02',
                        '2020-02-02T12:00:00', '2020-02-02T00:00:00Z', '20200202T00:00:00'):
                series = self.series()
                series['data'][position]['tradeDate'] = bad
                result = self.assess(series)
                self.assertIn('SERIES_SESSION_DATE_INVALID', result['reasons'])
                self.assertEqual(len(result['rows']), 2)
                self.assertIsNone(result['rows'][position]['date'])
                self.assertIsNone(result['series_asof'])

    def test_duplicates_reversal_and_unsorted_not_repaired(self):
        for second in ('2020-02-02T00:00:00', '2020-02-01T00:00:00'):
            series = self.series()
            series['data'][1]['tradeDate'] = second
            result = self.assess(series)
            self.assertIn('SESSION_DATES_NOT_UNIQUE_CHRONOLOGICAL', result['reasons'])
            self.assertEqual(result['rows'][1]['raw']['tradeDate'], second)
            self.assertIsNone(result['series_asof'])

    def test_explicit_window_and_asof_fail_closed_no_trim(self):
        result = self.assess(window_start='2020-02-03')
        self.assertIn('SERIES_ROW_OUTSIDE_EXPLICIT_DATE_WINDOW', result['reasons'])
        self.assertEqual(result['row_count'], 2)
        result = self.assess(window_end='2020-02-04', expected_asof='2020-02-04')
        self.assertIn('SERIES_EXPECTED_ASOF_NOT_MET', result['reasons'])
        self.assertEqual(result['freshness_status'], 'UNRESOLVED')
        self.assertEqual(result['series_asof'], '2020-02-03')

    def test_different_endpoint_freshness_is_not_spliced(self):
        series = self.series()
        series['data'].append({'isinCode': 'INVENTED001', 'name': 'Example Equity',
                               'tradeDate': '2020-02-04T00:00:00', 'closePrice': 15, 'tradeVolume': 5})
        series['totalCount'] = 3
        result = self.assess(series, requested_days=180,
                             receipt_patch={'url': 'https://beta.egx.com.eg/api/bff/egx/price-volume-points?isin=INVENTED001&date=180',
                                            'final_url': 'https://beta.egx.com.eg/api/bff/egx/price-volume-points?isin=INVENTED001&date=180'})
        self.assertEqual(result['row_count'], 3)
        self.assertIn('SERIES_ROW_OUTSIDE_EXPLICIT_DATE_WINDOW', result['reasons'])
        self.assertIn('SERIES_EXPECTED_ASOF_NOT_MET', result['reasons'])
        self.assertEqual(len(self.assess()['rows']), 2)

    def test_action_boundary_and_unresolved_policy(self):
        series = self.series()
        series['data'][0]['tradeDate'] = '2020-01-31T00:00:00'
        result = self.assess(series)
        self.assertIn('SERIES_CROSSES_UNRESOLVED_ACTION_BOUNDARY', result['reasons'])
        for changes in ({'admissible_since': None}, {'policy_source_url': None},
                        {'window_start': 'bad'}, {'window_end': '2020-02-01'},
                        {'expected_asof': '2020-02-05'}, {'admissible_since': '2020-02-03'}):
            self.assertIn('EXPLICIT_DATE_WINDOW_ASOF_OR_POST_ACTION_POLICY_UNRESOLVED',
                          self.assess(**changes)['reasons'])

    def test_receipt_body_and_owning_endpoint_conflicts_matrix(self):
        for patch in ({'sha256': 'bad'}, {'bytes': 1}, {'status': 404},
                      {'url': 'https://elsewhere.example/api'},
                      {'final_url': 'http://beta.egx.com.eg/api/bff/egx/price-volume-points?isin=INVENTED001&date=30'},
                      {'url': 'https://beta.egx.com.eg/api/bff/egx/price-volume-points?isin=OTHER&date=30'},
                      {'url': 'https://beta.egx.com.eg/api/bff/egx/price-volume-points?isin=INVENTED001&date=180'},
                      {'retrieved_utc': '2020-02-04T18:00:00'}):
            result = self.assess(receipt_patch=patch)
            self.assertEqual(result['decision'], 'REFUSE')
            self.assertEqual(result['row_count'], 2)
        result = self.assess(reference_receipt_patch={'sha256': 'bad'})
        self.assertIn('RECEIPT_BODY_BINDING_CONFLICT', result['reasons'])
        result = self.assess(reference_receipt_patch={'final_url': 'https://elsewhere.example'})
        self.assertIn('OWNING_ENDPOINT_OR_REQUEST_CONFLICT', result['reasons'])

    def test_future_session_dates_and_reference_future_date(self):
        result = self.assess(receipt_patch={'retrieved_utc': '2020-02-01T18:00:00Z'})
        self.assertIn('SERIES_DATE_AFTER_RETRIEVAL', result['reasons'])
        result = self.assess(reference_receipt_patch={'retrieved_utc': '2020-02-01T18:00:00Z'})
        self.assertIn('REFERENCE_DATE_AFTER_RETRIEVAL', result['reasons'])

    def test_provider_status_count_and_small_series(self):
        for patch, reason in [({'success': False}, 'SERIES_PROVIDER_FAILURE'),
                              ({'totalCount': 99}, 'SERIES_COUNT_CONFLICT'),
                              ({'totalCount': True}, 'SERIES_COUNT_CONFLICT')]:
            series = self.series()
            series.update(patch)
            result = self.assess(series)
            self.assertIn(reason, result['reasons'])
            self.assertEqual(result['row_count'], 2)
        for size in (0, 1):
            series = self.series()
            series['data'] = series['data'][:size]
            series['totalCount'] = size
            self.assertIn('FEWER_THAN_TWO_DATES', self.assess(series)['reasons'])

    def test_unavailable_schema_and_reference_cardinality(self):
        for series in (None, [], {}, {'data': None}):
            result = self.assess(series)
            self.assertEqual(result['inventory_status'], 'UNAVAILABLE')
            self.assertIn('SERIES_SCHEMA_INVALID', result['reasons'])
        for reference in (None, [], {}, {'data': []}, {'data': [None]},
                          {'data': [{}, {}]}):
            result = self.assess(reference=reference)
            self.assertIn('REFERENCE_SINGLE_IDENTITY_UNRESOLVED', result['reasons'])
            self.assertEqual(result['row_count'], 2)

    def test_bad_json_duplicate_keys_and_nonbytes(self):
        for raw in (b'{', b'{"data":[],"data":[]}', b'\xff'):
            result = self.assess(raw_series=raw)
            self.assertIn('RESPONSE_JSON_INVALID', result['reasons'])
            self.assertEqual(result['inventory_status'], 'UNAVAILABLE')
        result = assess_egx_close_volume(None, None, series_receipt=None, reference_receipt=None,
                                         requested_isin='X', requested_symbol='Y', requested_days=30,
                                         window_start=None, window_end=None, expected_asof=None,
                                         admissible_since=None, policy_source_url=None)
        self.assertIn('RAW_BYTES_REQUIRED', result['reasons'])
        self.assertIn('RECEIPT_UNAVAILABLE', result['reasons'])

    def test_input_not_mutated_and_range_parameter_not_exact_calendar_window(self):
        series = self.series()
        reference = self.reference()
        before = copy.deepcopy((series, reference))
        self.assess(series, reference)
        self.assertEqual((series, reference), before)
        self.assertIn('REQUEST_IDENTITY_OR_RANGE_INVALID', self.assess(requested_days=True)['reasons'])
        self.assertEqual(self.assess()['freshness_status'],
                         'MATCHES_EXPLICIT_HISTORICAL_ASOF_NOT_LATEST_SESSION')

    def test_ui_synthetic_ohlc_or_adjusted_fields_not_accepted(self):
        for field in ('openPrice', 'high', 'low', 'adjclose', 'currency'):
            series = self.series()
            series['data'][0][field] = 12.0
            result = self.assess(series)
            self.assertIn('SERIES_UNEXPECTED_FIELDS_NO_OHLC_OR_ADJUSTED_INFERENCE', result['reasons'])
            self.assertIn(field, result['rows'][0]['raw'])
            self.assertEqual(len(result['rows']), 2)

    def test_missing_count_or_receipt_size_types_fail_closed(self):
        series = self.series()
        del series['totalCount']
        self.assertIn('SERIES_COUNT_CONFLICT', self.assess(series)['reasons'])
        reference = self.reference()
        del reference['totalCount']
        self.assertIn('REFERENCE_COUNT_CONFLICT', self.assess(reference=reference)['reasons'])
        raw = self.encode(self.series())
        result = self.assess(receipt_patch={'bytes': float(len(raw))})
        self.assertIn('RECEIPT_BODY_BINDING_CONFLICT', result['reasons'])

    def test_reference_date_invalid_and_error_do_not_replace_series_asof(self):
        for value in (None, '2020-02-02', '2020-02-30T00:00:00'):
            reference = self.reference()
            reference['data'][0]['lasT_TRADE_DATE'] = value
            result = self.assess(reference=reference)
            self.assertIn('REFERENCE_DATE_INVALID', result['reasons'])
            self.assertEqual(result['series_asof'], '2020-02-03')
        reference = self.reference()
        reference['success'] = False
        result = self.assess(reference=reference)
        self.assertIn('REFERENCE_PROVIDER_FAILURE', result['reasons'])
        self.assertEqual(result['row_count'], 2)

    def test_same_date_header_conflict_refuses_but_different_date_not_latest_quote(self):
        reference = self.reference()
        reference['data'][0]['lasT_CP'] = 700.0
        result = self.assess(reference=reference)
        self.assertIn('SAME_DATE_REFERENCE_SERIES_CLOSE_CONFLICT', result['reasons'])
        self.assertEqual(result['rows'][0]['raw']['closePrice'], 12.0)
        reference['data'][0]['lasT_TRADE_DATE'] = '2020-02-01T00:00:00'
        result = self.assess(reference=reference)
        self.assertNotIn('SAME_DATE_REFERENCE_SERIES_CLOSE_CONFLICT', result['reasons'])
        self.assertFalse(result['current_quote_usable'])
        self.assertEqual(result['reference_asof'], '2020-02-01T00:00:00')
        self.assertEqual(result['series_asof'], '2020-02-03')

    def test_invalid_header_close_is_not_used_to_fill_series(self):
        for bad in (None, True, '12', -1, 0, float('inf')):
            reference = self.reference()
            reference['data'][0]['lasT_CP'] = bad
            result = self.assess(reference=reference)
            self.assertIn('REFERENCE_HEADER_CLOSE_INVALID', result['reasons'])
            self.assertEqual(result['rows'][0]['raw']['closePrice'], 12.0)

    def test_ambiguous_endpoint_query_and_missing_receipts_refuse_without_losing_rows(self):
        for url in ('https://beta.egx.com.eg/api/bff/egx/price-volume-points?isin=INVENTED001&date=30&date=180',
                    'https://beta.egx.com.eg/api/bff/egx/price-volume-points?isin=INVENTED001&date=30#fragment',
                    'https://beta.egx.com.eg.evil.example/api/bff/egx/price-volume-points?isin=INVENTED001&date=30'):
            result = self.assess(receipt_patch={'url': url})
            self.assertIn('OWNING_ENDPOINT_OR_REQUEST_CONFLICT', result['reasons'])
            self.assertEqual(result['row_count'], 2)
        result = self.assess(series_receipt=None, reference_receipt=None)
        self.assertIn('RECEIPT_UNAVAILABLE', result['reasons'])
        self.assertEqual(result['row_count'], 2)
        self.assertEqual(result['rows'][0]['raw']['closePrice'], 12.0)


if __name__ == '__main__':
    unittest.main()
