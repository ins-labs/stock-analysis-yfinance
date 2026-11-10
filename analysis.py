"""Public yfinance price-history analysis. No trades, credentials or holdings."""
import argparse
import json
import math
import re
from collections.abc import Mapping
from numbers import Real
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PERIODS = ('1mo', '3mo', '6mo', '1y', '2y', '5y')


def ticker_list(value):
    values = [v.strip().upper() for v in value.split(',')]
    if not 1 <= len(values) <= 10 or any(not re.fullmatch(r'[A-Z0-9^][A-Z0-9.^=-]{0,24}', v) for v in values):
        raise argparse.ArgumentTypeError('Use 1-10 comma-separated ticker symbols, no paths or shell commands')
    return list(dict.fromkeys(values))


def summarize(frame):
    # Fail closed: never drop missing rows or silently coerce text/bool prices.
    import pandas as pd
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or 'Close' not in frame:
        raise ValueError('A single Close column is required')
    close = frame['Close']
    if len(close) < 2:
        raise ValueError('At least two dated close prices are required')
    index = close.index
    if (not isinstance(index, pd.DatetimeIndex) or index.hasnans
            or not index.is_unique or not index.is_monotonic_increasing):
        raise ValueError('A dated, unique, chronological index is required')
    # This daily-history contract rejects multiple observations of one date.
    dates = [stamp.date() for stamp in index]
    if len(set(dates)) != len(dates):
        raise ValueError('Distinct daily dates are required')
    values = []
    for value in close:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError('Every close price must be numeric')
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError('Every close price must be finite and positive')
        values.append(number)
    first, last = values[0], values[-1]
    change = (last / first - 1) * 100
    if not math.isfinite(change):
        raise ValueError('Adjusted price change must be finite')
    dividends = None
    if 'Dividends' in frame:
        dividend_values = []
        for value in frame['Dividends']:
            if pd.isna(value):
                dividend_values.append(0.0)
            elif isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
                raise ValueError('Dividend events must be finite numeric values')
            else:
                dividend_values.append(float(value))
        dividends = sum(dividend_values)
        if not math.isfinite(dividends):
            raise ValueError('Dividend sum must be finite')
    return {'rows': len(values), 'first_date': str(index[0]), 'last_date': str(index[-1]),
            'first_adjusted_close': first, 'last_adjusted_close': last,
            'adjusted_price_change_pct': change,
            'dividends_in_returned_window': dividends}


def admit_history(frame, requested_symbol, metadata):
    # Provider-returned history metadata is separate evidence from the request.
    if not isinstance(metadata, Mapping):
        raise ValueError('Provider history metadata is required')
    provider_symbol = metadata.get('symbol')
    if (not isinstance(provider_symbol, str) or not provider_symbol
            or provider_symbol != provider_symbol.strip()
            or provider_symbol != requested_symbol):
        raise ValueError('Provider symbol must exactly match the requested symbol')
    fields = {}
    for key in ('currency', 'exchangeTimezoneName'):
        value = metadata.get(key)
        if (not isinstance(value, str) or not value.strip()
                or value != value.strip() or value.upper() in ('UNKNOWN', 'N/A', 'NULL', 'NONE')):
            raise ValueError('Nonempty provider currency and timezone are required')
        fields[key] = value
    try:
        ZoneInfo(fields['exchangeTimezoneName'])
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError('A recognized provider timezone is required') from error
    summary = summarize(frame)
    if frame.index.tz is not None and str(frame.index.tz) != fields['exchangeTimezoneName']:
        raise ValueError('History index timezone must match provider timezone')
    summary.update(requested_ticker=requested_symbol, provider_ticker=provider_symbol,
                   currency=fields['currency'], exchange_timezone=fields['exchangeTimezoneName'])
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', required=True, type=ticker_list)
    parser.add_argument('--period', choices=PERIODS, required=True)
    args = parser.parse_args(argv)
    import yfinance as yf
    reports, failures = [], []
    for symbol in args.tickers:
        try:
            ticker = yf.Ticker(symbol)
            frame = ticker.history(period=args.period, auto_adjust=True, actions=True, raise_errors=True)
            metadata = ticker.get_history_metadata()
            summary = admit_history(frame, symbol, metadata)
            summary.update(ticker=symbol, period=args.period)
            print(json.dumps(summary, sort_keys=True, allow_nan=False))
            reports.append(summary)
        except Exception as error:
            # Public provider errors, not a fake successful empty analysis.
            failures.append({'ticker': symbol, 'error_type': type(error).__name__})
            print(json.dumps(failures[-1]))
    print(json.dumps({'analysis_count': len(reports), 'failure_count': len(failures),
        'data_source': 'Yahoo Finance via yfinance; historical data may be delayed or revised',
        'interpretation': 'Adjusted price change, not a trade recommendation or guaranteed return'}))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
