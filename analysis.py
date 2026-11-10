"""Public yfinance price-history analysis. No trades, credentials or holdings."""
import argparse
import json
import math
import re

PERIODS = ('1mo', '3mo', '6mo', '1y', '2y', '5y')


def ticker_list(value):
    values = [v.strip().upper() for v in value.split(',')]
    if not 1 <= len(values) <= 10 or any(not re.fullmatch(r'[A-Z0-9^][A-Z0-9.^=-]{0,24}', v) for v in values):
        raise argparse.ArgumentTypeError('Use 1-10 comma-separated ticker symbols, no paths or shell commands')
    return list(dict.fromkeys(values))


def summarize(frame):
    close = frame['Close'].dropna()
    if len(close) < 2:
        raise ValueError('At least two dated nonempty close prices are required')
    first, last = float(close.iloc[0]), float(close.iloc[-1])
    if not all(math.isfinite(v) and v > 0 for v in (first, last)):
        raise ValueError('Invalid close prices')
    return {'rows': len(close), 'first_date': str(close.index[0]), 'last_date': str(close.index[-1]),
            'first_adjusted_close': first, 'last_adjusted_close': last,
            'adjusted_price_change_pct': (last / first - 1) * 100,
            'dividends_in_returned_window': float(frame['Dividends'].fillna(0).sum()) if 'Dividends' in frame else None}


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
            summary = summarize(frame)
            metadata = ticker.get_history_metadata() or {}
            summary.update(ticker=symbol, period=args.period, currency=metadata.get('currency', 'UNKNOWN'),
                           exchange_timezone=metadata.get('exchangeTimezoneName', 'UNKNOWN'))
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
