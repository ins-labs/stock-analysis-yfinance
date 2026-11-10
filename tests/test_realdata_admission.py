"""PRIVATE SOURCE ONLY / UNRUN. Invented data, no provider or network calls."""
import contextlib
import io
import json
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd
import analysis


class RealDataAdmissionTests(unittest.TestCase):
    def frame(self, values=None, dates=None):
        return pd.DataFrame({'Close': [10.0, 11.0, 12.0] if values is None else values},
                            index=pd.to_datetime(['2026-01-01', '2026-01-02', '2026-01-03']
                                                 if dates is None else dates))

    def metadata(self):
        return {'symbol': 'EXAMPLE', 'currency': 'USD', 'exchangeTimezoneName': 'America/New_York'}

    def admit(self, frame=None, metadata=None):
        return analysis.admit_history(self.frame() if frame is None else frame,
                                      'EXAMPLE', self.metadata() if metadata is None else metadata)

    def test_valid_invented_series_and_separate_identity(self):
        result = self.admit()
        self.assertEqual(result['rows'], 3)
        self.assertAlmostEqual(result['adjusted_price_change_pct'], 20.0)
        self.assertEqual(result['requested_ticker'], 'EXAMPLE')
        self.assertEqual(result['provider_ticker'], 'EXAMPLE')
        self.assertEqual(result['currency'], 'USD')
        self.assertEqual(result['exchange_timezone'], 'America/New_York')

    def test_every_position_refuses_nonfinite_nonpositive_missing(self):
        for bad in (float('nan'), float('inf'), -float('inf'), 0.0, -1.0, None, pd.NA):
            for position in range(3):
                values = [10.0, 11.0, 12.0]
                values[position] = bad
                with self.subTest(bad=repr(bad), position=position), self.assertRaises(ValueError):
                    self.admit(self.frame(values))

    def test_text_and_boolean_are_not_coerced(self):
        for bad in ('11.0', 'not-a-price', True, False):
            frame = self.frame()
            frame['Close'] = pd.Series([10.0, bad, 12.0], index=frame.index, dtype=object)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.admit(frame)

    def test_empty_single_row_and_missing_close_refused(self):
        for frame in (pd.DataFrame({'Close': []}), self.frame().iloc[:1],
                      self.frame().rename(columns={'Close': 'Open'})):
            with self.subTest(shape=frame.shape), self.assertRaises(ValueError):
                self.admit(frame)

    def test_duplicate_columns_refused(self):
        frame = self.frame()
        frame = pd.concat([frame, frame], axis=1)
        with self.assertRaises(ValueError):
            self.admit(frame)

    def test_numeric_and_string_indexes_not_inferred_as_dates(self):
        for index in ([1, 2, 3], ['2026-01-01', '2026-01-02', '2026-01-03']):
            frame = self.frame()
            frame.index = index
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.admit(frame)

    def test_nat_duplicate_and_reversed_dates_refused(self):
        for dates in (['2026-01-01', None, '2026-01-03'],
                      ['2026-01-01', '2026-01-01', '2026-01-03'],
                      ['2026-01-03', '2026-01-02', '2026-01-01'],
                      ['2026-01-01', '2026-01-03', '2026-01-02']):
            with self.subTest(dates=dates), self.assertRaises(ValueError):
                self.admit(self.frame(dates=dates))

    def test_multiple_observations_same_daily_date_refused(self):
        dates = ['2026-01-01 10:00', '2026-01-01 11:00', '2026-01-02 10:00']
        with self.assertRaises(ValueError):
            self.admit(self.frame(dates=dates))

    def test_missing_nonmapping_provider_metadata_refused(self):
        for metadata in (None, [], 'EXAMPLE'):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                analysis.admit_history(self.frame(), 'EXAMPLE', metadata)

    def test_missing_blank_and_mismatched_provider_symbol_refused(self):
        for symbol in (None, '', ' ', 'OTHER', 'example', 'EXAMPLE ', 12):
            metadata = self.metadata()
            metadata['symbol'] = symbol
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                self.admit(metadata=metadata)
        metadata = self.metadata()
        del metadata['symbol']
        with self.assertRaises(ValueError):
            self.admit(metadata=metadata)

    def test_currency_timezone_missing_empty_placeholder_refused(self):
        for key in ('currency', 'exchangeTimezoneName'):
            for value in (None, '', ' ', 'UNKNOWN', 'unknown', 'N/A', 'NULL', 'NONE', 1, ' USD '):
                metadata = self.metadata()
                metadata[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.admit(metadata=metadata)
            metadata = self.metadata()
            del metadata[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.admit(metadata=metadata)

    def test_unrecognized_timezone_refused(self):
        metadata = self.metadata()
        metadata['exchangeTimezoneName'] = 'Not/A_Zone'
        with self.assertRaises(ValueError):
            self.admit(metadata=metadata)

    def test_aware_index_timezone_match_required(self):
        frame = self.frame()
        frame.index = frame.index.tz_localize('America/New_York')
        self.assertEqual(self.admit(frame)['rows'], 3)
        frame.index = frame.index.tz_convert('UTC')
        with self.assertRaises(ValueError):
            self.admit(frame)

    def test_valid_main_keeps_both_identity_fields(self):
        frame, metadata = self.frame(), self.metadata()
        fake_ticker = types.SimpleNamespace(history=lambda **kwargs: frame,
                                             get_history_metadata=lambda: metadata)
        output = io.StringIO()
        with patch.dict(sys.modules, {'yfinance': types.SimpleNamespace(Ticker=lambda symbol: fake_ticker)}), contextlib.redirect_stdout(output):
            rc = analysis.main(['--tickers', 'EXAMPLE', '--period', '1y'])
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rc, 0)
        self.assertEqual(lines[0]['provider_ticker'], 'EXAMPLE')
        self.assertEqual(lines[0]['requested_ticker'], 'EXAMPLE')
        self.assertEqual(lines[-1]['analysis_count'], 1)
        self.assertEqual(lines[-1]['failure_count'], 0)

    def test_nonfinite_computed_change_refused(self):
        with self.assertRaises(ValueError):
            self.admit(self.frame([5e-324, 1.0, 1e308]))

    def test_dividend_values_and_sum_cannot_leak_nonfinite(self):
        for values in ([0.0, float('inf'), 0.0], [1e308, 1e308, 0.0], [0.0, '1', 0.0]):
            frame = self.frame()
            frame['Dividends'] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.admit(frame)
        frame = self.frame()
        frame['Dividends'] = [0.0, None, 0.5]
        self.assertEqual(self.admit(frame)['dividends_in_returned_window'], 0.5)

    def test_main_refuses_before_public_summary_and_reports_failure(self):
        # No yfinance or network call: inject a fake module for integration wiring.
        for invalid in ('interior', 'identity', 'currency', 'timezone'):
            frame, metadata = self.frame(), self.metadata()
            if invalid == 'interior':
                frame.iloc[1, 0] = float('nan')
            elif invalid == 'identity':
                metadata['symbol'] = 'OTHER'
            else:
                metadata.pop('exchangeTimezoneName' if invalid == 'timezone' else 'currency')
            fake_ticker = types.SimpleNamespace(history=lambda **kwargs: frame,
                                                 get_history_metadata=lambda: metadata)
            fake_module = types.SimpleNamespace(Ticker=lambda symbol: fake_ticker)
            output = io.StringIO()
            with self.subTest(invalid=invalid), patch.dict(sys.modules, {'yfinance': fake_module}), contextlib.redirect_stdout(output):
                rc = analysis.main(['--tickers', 'EXAMPLE', '--period', '1y'])
            lines = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(rc, 1)
            self.assertEqual(lines[0], {'ticker': 'EXAMPLE', 'error_type': 'ValueError'})
            self.assertEqual(lines[-1]['analysis_count'], 0)
            self.assertEqual(lines[-1]['failure_count'], 1)
            self.assertNotIn('first_adjusted_close', output.getvalue())


if __name__ == '__main__':
    unittest.main()
