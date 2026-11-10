"""Source-only chart assessment. No requests, alias repairs, or selected series.

Inventory precedes interpretation. Partial or unusable schema is explicitly marked.
External identity references are caller-supplied evidence, not authenticated here.
"""
from collections.abc import Mapping
from datetime import datetime
import math
from numbers import Real
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


FIELDS = ('open', 'high', 'low', 'close', 'volume', 'adjclose')


def assess_chart(payload, *, requested_symbol, source_endpoint, retrieved_at,
                 expected_instrument_type=None, identity_source_url=None,
                 period_start=None, period_end=None):
    """Retain available positional evidence and independently refuse defects.

    OHLC and adjclose must be finite numeric values > 0, volume >= 0.
    Booleans and numeric strings are not numbers here. Fractional volume is not
    rounded or rejected as nonintegral. No OHLC relationship is manufactured.
    Windows are [start, end). Missing array slots differ from explicit nulls.
    """
    result = {'decision': 'REFUSE', 'requested_symbol': requested_symbol,
              'source_endpoint': source_endpoint, 'retrieved_at': None,
              'provider_symbol': None, 'provider_instrument_type': None,
              'identity_source_url': identity_source_url,
              'expected_instrument_type': expected_instrument_type,
              'series_asof': None, 'row_count': 0, 'timestamp_count': None,
              'rows': [], 'reasons': [], 'inventory_status': 'UNAVAILABLE',
              'inventory_issues': [], 'provider_quote_timestamp': None,
              'quote_usable_as_series_current_quote': False,
              'adjustment_status': 'ADJCLOSE_ARRAY_UNAVAILABLE_NOT_QUALIFIED'}

    def refuse(reason):
        if reason not in result['reasons']:
            result['reasons'].append(reason)

    def finite(value):
        try:
            return (isinstance(value, Real) and not isinstance(value, bool)
                    and math.isfinite(value))
        except (OverflowError, TypeError, ValueError):
            return False

    def label(value):
        return (isinstance(value, str) and bool(value.strip())
                and value == value.strip()
                and value.upper() not in ('UNKNOWN', 'NULL', 'NONE', 'N/A'))

    def issue(detail):
        result['inventory_issues'].append(detail)
        refuse('RESPONSE_SCHEMA_INVALID')

    # Select no record from an ambiguous multi-result response.
    chart = payload.get('chart') if isinstance(payload, Mapping) else None
    if not isinstance(chart, Mapping):
        chart = {}
        issue('chart mapping unavailable')
    if chart.get('error') is not None:
        refuse('PROVIDER_ERROR')
    records = chart.get('result')
    if not (isinstance(records, list) and len(records) == 1
            and isinstance(records[0], Mapping)):
        issue('single result mapping unavailable; no record selected')
        return result
    record = records[0]
    meta = record.get('meta')
    if not isinstance(meta, Mapping):
        meta = {}
        issue('metadata mapping unavailable')
    timestamps = record.get('timestamp')
    if not isinstance(timestamps, list):
        timestamps = None
        issue('timestamp array unavailable')
    else:
        result['timestamp_count'] = len(timestamps)
    indicators = record.get('indicators')
    if not isinstance(indicators, Mapping):
        indicators = {}
        issue('indicators mapping unavailable')

    def sole_mapping(key):
        values = indicators.get(key)
        if not (isinstance(values, list) and len(values) == 1
                and isinstance(values[0], Mapping)):
            issue(key + ' singleton mapping unavailable; no array group selected')
            return {}
        return values[0]

    quote = sole_mapping('quote')
    adjusted = sole_mapping('adjclose')
    fields = {}
    for key in FIELDS:
        value = (adjusted if key == 'adjclose' else quote).get(key)
        if not isinstance(value, list):
            fields[key] = None
            issue(key + ' array unavailable')
        else:
            fields[key] = value
    if fields['adjclose'] is not None:
        result['adjustment_status'] = 'PROVIDER_ADJCLOSE_PRESENT_NOT_INDEPENDENTLY_QUALIFIED'
    arrays = ([timestamps] if timestamps is not None else []) + [
        value for value in fields.values() if value is not None]
    span = max((len(value) for value in arrays), default=0)
    if timestamps is not None and any(value is not None and len(value) != len(timestamps)
                                      for value in fields.values()):
        issue('array lengths differ; positional span retained without aligning or filling')
    result['inventory_status'] = ('PARTIAL' if result['inventory_issues'] else 'COMPLETE')
    if not arrays:
        result['inventory_status'] = 'UNAVAILABLE'
    for position in range(span):
        available = {key: value[position] for key, value in fields.items()
                     if value is not None and position < len(value)}
        stamp_available = timestamps is not None and position < len(timestamps)
        result['rows'].append({
            'position': position, 'timestamp_available': stamp_available,
            'timestamp': timestamps[position] if stamp_available else None,
            'date': None, 'date_status': 'UNRESOLVED', 'values': available,
            'unavailable_fields': [key for key in FIELDS if key not in available],
            'missing_fields': [key for key, value in available.items() if value is None],
            'invalid_fields': [key for key, value in available.items()
                               if not finite(value) or (value < 0 if key == 'volume' else value <= 0)],
            'session_status': 'UNKNOWN', 'in_requested_window': None})
    result['row_count'] = span

    observed = None
    if (not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None
            or retrieved_at.utcoffset() is None):
        refuse('RETRIEVAL_TIME_NOT_AWARE')
    else:
        result['retrieved_at'] = retrieved_at.isoformat()
        try:
            observed = retrieved_at.timestamp()
        except (OverflowError, OSError, ValueError):
            refuse('RETRIEVAL_TIME_OUT_OF_RANGE')
    if not label(requested_symbol) or not label(source_endpoint):
        refuse('REQUEST_PROVENANCE_MISSING')
    window_valid = not ((period_start is None) != (period_end is None))
    if period_start is not None:
        window_valid = (window_valid and finite(period_start) and finite(period_end)
                        and period_start < period_end)
    if not window_valid:
        refuse('REQUEST_WINDOW_INVALID')
    result['provider_symbol'] = meta.get('symbol')
    result['provider_instrument_type'] = meta.get('instrumentType')
    result['currency'] = meta.get('currency')
    result['exchange_timezone'] = meta.get('exchangeTimezoneName')
    if not label(meta.get('symbol')) or meta.get('symbol') != requested_symbol:
        refuse('PROVIDER_SYMBOL_MISMATCH_OR_MISSING')
    if not label(expected_instrument_type) or not label(identity_source_url):
        refuse('EXTERNAL_INSTRUMENT_IDENTITY_UNRESOLVED')
    elif meta.get('instrumentType') != expected_instrument_type:
        refuse('PROVIDER_INSTRUMENT_TYPE_CONFLICT')
    if not label(meta.get('currency')):
        refuse('CURRENCY_MISSING')
    zone = None
    try:
        if not label(meta.get('exchangeTimezoneName')):
            raise ValueError('timezone missing')
        zone = ZoneInfo(meta['exchangeTimezoneName'])
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        refuse('TIMEZONE_INVALID')
    if timestamps is None or len(timestamps) < 2:
        refuse('FEWER_THAN_TWO_DATES')
    valid_stamps = timestamps is not None and all(finite(t) for t in timestamps)
    if not valid_stamps or any(a >= b for a, b in zip(timestamps, timestamps[1:])):
        refuse('TIMESTAMPS_INVALID_OR_NOT_UNIQUE_CHRONOLOGICAL')

    start = end = session_date = None
    session_state = 'UNKNOWN'
    try:
        regular = meta['currentTradingPeriod']['regular']
        if not isinstance(regular, Mapping):
            raise ValueError('session mapping unavailable')
        start, end = regular['start'], regular['end']
        if not finite(start) or not finite(end) or not start < end:
            raise ValueError('invalid session')
        result['provider_regular_session'] = {'start': start, 'end': end,
                                               'state_at_retrieval': 'UNKNOWN'}
        if observed is not None:
            session_state = 'OPEN_OR_NOT_CLOSED' if observed < end else 'CLOSED'
            result['provider_regular_session']['state_at_retrieval'] = session_state
        if zone is not None:
            session_date = datetime.fromtimestamp(start, zone).date().isoformat()
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        start = end = session_date = None
        refuse('PROVIDER_SESSION_EVIDENCE_MISSING')
    dates = []
    for row in result['rows']:
        stamp = row['timestamp']
        stamp_valid = row['timestamp_available'] and finite(stamp)
        row['date_status'] = ('TIMESTAMP_UNAVAILABLE' if not row['timestamp_available']
                              else 'TIMESTAMP_INVALID' if not stamp_valid
                              else 'TIMEZONE_UNRESOLVED')
        if window_valid and stamp_valid:
            row['in_requested_window'] = period_start is None or period_start <= stamp < period_end
            if not row['in_requested_window']:
                refuse('PROVIDER_ROW_OUTSIDE_REQUESTED_WINDOW')
        if stamp_valid and observed is not None and stamp > observed:
            refuse('FUTURE_BAR_TIMESTAMP')
        if stamp_valid and zone is not None:
            try:
                row['date'] = datetime.fromtimestamp(stamp, zone).date().isoformat()
                row['date_status'] = 'RESOLVED'
                dates.append(row['date'])
            except (OverflowError, OSError, ValueError):
                row['date_status'] = 'TIMESTAMP_OUT_OF_RANGE'
                refuse('TIMESTAMPS_OUT_OF_RANGE')
        date = row['date']
        if date is not None and session_date is not None:
            row['session_status'] = session_state if date == session_date else 'NOT_CURRENT_SESSION'
            if date > session_date:
                refuse('BAR_AFTER_KNOWN_PROVIDER_SESSION')
            if date == session_date and session_state == 'OPEN_OR_NOT_CLOSED':
                refuse('CURRENT_SESSION_NOT_CLOSED')
        if row['invalid_fields'] or row['unavailable_fields']:
            refuse('INVALID_PRICE_ROW')
            if (row['position'] == span - 1 and len(row['missing_fields']) == 6
                    and not row['unavailable_fields'] and stamp_valid
                    and date is not None and date == session_date
                    and start <= stamp <= end):
                if session_state == 'CLOSED':
                    refuse('MISSING_BAR_AFTER_PROVIDER_SESSION_CLOSE')
                elif session_state == 'OPEN_OR_NOT_CLOSED':
                    refuse('UNFINISHED_CURRENT_BAR_REQUIRES_EXPLICIT_SELECTION')
    if len(set(dates)) != len(dates):
        refuse('DUPLICATE_DAILY_DATE')
    if (timestamps and valid_stamps and not result['inventory_issues']
            and all(row['date'] is not None for row in result['rows'])
            and all(a < b for a, b in zip(timestamps, timestamps[1:]))):
        result['series_asof'] = result['rows'][-1]['date']
    quote_time = meta.get('regularMarketTime')
    result['provider_quote_timestamp'] = quote_time
    if not finite(quote_time) or (valid_stamps and timestamps and quote_time < max(timestamps)):
        refuse('QUOTE_TIMESTAMP_MISSING_OR_OLDER_THAN_SERIES')
    if not result['reasons']:
        result['decision'] = 'STRUCTURAL_CHECKS_CLEAR_NOT_FINANCIAL_QUALIFICATION'
    return result
