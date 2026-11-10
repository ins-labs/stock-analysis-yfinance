"""Source-specific official EGX date-label/close/volume assessment, no retrieval.

This does not relax chart_admission or select an adjusted financial dataset.
Receipt authenticity and policy evidence are caller responsibilities; hashes bind
supplied bytes, not their authorship. Returned raw inventory is private evidence.
"""
from collections.abc import Mapping
from datetime import date, datetime
import hashlib
import json
import math
from numbers import Real
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def assess_egx_close_volume(series_bytes, reference_bytes, *, series_receipt,
                            reference_receipt, requested_isin, requested_symbol,
                            requested_days, window_start, window_end,
                            expected_asof, admissible_since, policy_source_url):
    """Assess the entire response, never filter, splice, fill or compute returns.

    window_start/end are inclusive session-date labels, not endpoint `date` days
    inferred into exact calendar bounds. expected_asof is the explicit required
    historical endpoint, not a claim of the latest exchange session. The caller
    supplies the allowed post-action boundary and its reviewed evidence source.
    No reference header price is substituted into series rows.
    """
    out = {'decision': 'REFUSE', 'reasons': [], 'rows': [], 'row_count': 0,
           'inventory_status': 'UNAVAILABLE', 'inventory_issues': [],
           'requested_isin': requested_isin, 'requested_symbol': requested_symbol,
           'requested_days': requested_days, 'provider_symbol': None,
           'series_asof': None, 'reference_asof': None,
           'currency': None, 'currency_provenance': None,
           'timestamp_semantics': 'SESSION_DATE_LABEL_NOT_AN_INSTANT_OR_CLOSED_SESSION',
           'freshness_status': 'UNRESOLVED', 'current_quote_usable': False,
           'adjustment_status': 'UNADJUSTED_CLOSE_ONLY_CORPORATE_ACTIONS_UNRESOLVED',
           'policy_source_url': policy_source_url,
           'session_calendar_completeness': 'UNVERIFIED_NO_HOLIDAY_OR_SESSION_CLOSE_INFERENCE'}

    def refuse(code):
        if code not in out['reasons']:
            out['reasons'].append(code)

    def finite(value):
        try:
            return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
        except (OverflowError, TypeError, ValueError):
            return False

    def label(value):
        return isinstance(value, str) and bool(value) and value == value.strip()

    def day(value):
        if not isinstance(value, str):
            return None
        try:
            parsed = date.fromisoformat(value)
            return parsed if parsed.isoformat() == value else None
        except ValueError:
            return None

    def session_day(value):
        if not isinstance(value, str) or len(value) != 19 or value[10:] != 'T00:00:00':
            return None
        return day(value[:10])

    def aware(value):
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
        except (ValueError, OverflowError):
            return None

    def receipt_check(receipt, raw, path, query):
        if not isinstance(receipt, Mapping):
            refuse('RECEIPT_UNAVAILABLE')
            return None
        expected_query = {key: [str(value)] for key, value in query.items()}
        for key in ('url', 'final_url'):
            try:
                url = urlsplit(receipt.get(key))
                if (url.scheme != 'https' or url.netloc != 'beta.egx.com.eg'
                        or url.path != path or url.fragment
                        or parse_qs(url.query, keep_blank_values=True) != expected_query):
                    refuse('OWNING_ENDPOINT_OR_REQUEST_CONFLICT')
            except (AttributeError, TypeError, ValueError):
                refuse('OWNING_ENDPOINT_OR_REQUEST_CONFLICT')
        if (not isinstance(receipt.get('status'), int) or isinstance(receipt.get('status'), bool)
                or receipt.get('status') != 200):
            refuse('RECEIPT_STATUS_INVALID')
        if not isinstance(raw, bytes):
            refuse('RAW_BYTES_REQUIRED')
        elif (not isinstance(receipt.get('bytes'), int) or isinstance(receipt.get('bytes'), bool)
              or receipt.get('bytes') != len(raw)
              or receipt.get('sha256') != hashlib.sha256(raw).hexdigest()):
            refuse('RECEIPT_BODY_BINDING_CONFLICT')
        observed = aware(receipt.get('retrieved_utc'))
        if observed is None:
            refuse('RETRIEVAL_TIME_NOT_AWARE')
        return observed

    def decode(raw):
        if not isinstance(raw, bytes):
            refuse('RAW_BYTES_REQUIRED')
            return None
        try:
            # Duplicate keys are ambiguous, not silently last-value-wins.
            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('duplicate JSON key')
                    result[key] = value
                return result
            return json.loads(raw, object_pairs_hook=unique_pairs)
        except (UnicodeDecodeError, ValueError, TypeError):
            refuse('RESPONSE_JSON_INVALID')
            return None

    series = decode(series_bytes)
    reference = decode(reference_bytes)
    observed = receipt_check(series_receipt, series_bytes,
                             '/api/bff/egx/price-volume-points',
                             {'isin': requested_isin, 'date': requested_days})
    reference_observed = receipt_check(reference_receipt, reference_bytes,
                                       '/api/bff/egx/stock-info', {'Isin': requested_isin})
    out['series_receipt'] = dict(series_receipt) if isinstance(series_receipt, Mapping) else None
    out['reference_receipt'] = dict(reference_receipt) if isinstance(reference_receipt, Mapping) else None
    if (not label(requested_isin) or not label(requested_symbol)
            or not isinstance(requested_days, int) or isinstance(requested_days, bool)
            or requested_days <= 0):
        refuse('REQUEST_IDENTITY_OR_RANGE_INVALID')
    start, end, asof, guard = [day(value) for value in
                              (window_start, window_end, expected_asof, admissible_since)]
    policy_valid = (all(value is not None for value in (start, end, asof, guard))
                    and start <= asof <= end and guard <= start and label(policy_source_url))
    if not policy_valid:
        refuse('EXPLICIT_DATE_WINDOW_ASOF_OR_POST_ACTION_POLICY_UNRESOLVED')
    out['date_policy'] = {'start_inclusive': window_start, 'end_inclusive': window_end,
                          'expected_asof': expected_asof, 'admissible_since': admissible_since}

    def rows_from(body, kind):
        if not isinstance(body, Mapping) or not isinstance(body.get('data'), list):
            refuse(kind + '_SCHEMA_INVALID')
            return None
        if body.get('success') is not True:
            refuse(kind + '_PROVIDER_FAILURE')
        count = body.get('totalCount')
        if (not isinstance(count, int) or isinstance(count, bool)
                or count != len(body['data'])):
            refuse(kind + '_COUNT_CONFLICT')
        return body['data']

    records = rows_from(series, 'SERIES')
    refs = rows_from(reference, 'REFERENCE')
    ref_day = None
    civil_zone = None
    try:
        civil_zone = ZoneInfo('Africa/Cairo')
    except ZoneInfoNotFoundError:
        refuse('EXCHANGE_CIVIL_TIMEZONE_UNAVAILABLE')
    def civil_day(instant):
        if instant is None or civil_zone is None:
            return None
        try:
            return instant.astimezone(civil_zone).date()
        except (OverflowError, ValueError):
            refuse('RETRIEVAL_TIME_OUT_OF_RANGE')
            return None

    series_observed_day = civil_day(observed)
    reference_observed_day = civil_day(reference_observed)
    out['reference_inventory'] = refs
    ref = refs[0] if refs is not None and len(refs) == 1 and isinstance(refs[0], Mapping) else None
    if ref is None:
        refuse('REFERENCE_SINGLE_IDENTITY_UNRESOLVED')
    else:
        out['provider_symbol'] = ref.get('reuters')
        out['provider_name'] = ref.get('name')
        out['reference_asof'] = ref.get('lasT_TRADE_DATE')
        if (ref.get('isin') != requested_isin or ref.get('reuters') != requested_symbol
                or not label(ref.get('name'))
                or ref.get('schedule') != 'Egyptian securities-Stocks'):
            refuse('REFERENCE_IDENTITY_OR_EQUITY_CONFLICT')
        # Explicit owning-reference mapping, never inferred from the ticker or UI.
        if ref.get('curr') == 'L.E' and ref.get('curR_LONG') == 'Egyptian Pound':
            out['currency'] = 'EGP'
            out['currency_provenance'] = {'source': 'OWNING_STOCK_INFO_REFERENCE',
                                          'fields': {'curr': 'L.E', 'curR_LONG': 'Egyptian Pound'},
                                          'receipt_url': reference_receipt.get('url') if isinstance(reference_receipt, Mapping) else None,
                                          'body_sha256': reference_receipt.get('sha256') if isinstance(reference_receipt, Mapping) else None}
        else:
            refuse('REFERENCE_CURRENCY_UNRESOLVED')
        ref_day = session_day(ref.get('lasT_TRADE_DATE'))
        if ref_day is None:
            refuse('REFERENCE_DATE_INVALID')
        elif reference_observed_day is not None and ref_day > reference_observed_day:
            refuse('REFERENCE_DATE_AFTER_RETRIEVAL')
        if not finite(ref.get('lasT_CP')) or ref['lasT_CP'] <= 0:
            refuse('REFERENCE_HEADER_CLOSE_INVALID')

    dates = []
    if records is not None:
        out['inventory_status'] = 'COMPLETE'
        out['row_count'] = len(records)
        if len(records) < 2:
            refuse('FEWER_THAN_TWO_DATES')
        for position, raw in enumerate(records):
            row = {'position': position, 'raw': raw, 'date': None,
                   'missing_fields': [], 'invalid_fields': []}
            out['rows'].append(row)
            if not isinstance(raw, Mapping):
                out['inventory_status'] = 'PARTIAL'
                out['inventory_issues'].append({'position': position, 'issue': 'row not a mapping'})
                refuse('SERIES_ROW_SCHEMA_INVALID')
                continue
            for key in ('isinCode', 'name', 'tradeDate', 'closePrice', 'tradeVolume'):
                if key not in raw:
                    row['missing_fields'].append(key)
            unexpected = set(raw) - {'isinCode', 'name', 'nameAr', 'tradeDate', 'closePrice', 'tradeVolume'}
            if unexpected:
                row['unexpected_fields'] = sorted(unexpected)
                refuse('SERIES_UNEXPECTED_FIELDS_NO_OHLC_OR_ADJUSTED_INFERENCE')
            if row['missing_fields']:
                out['inventory_status'] = 'PARTIAL'
                refuse('SERIES_ROW_SCHEMA_INVALID')
            if (raw.get('isinCode') != requested_isin or ref is None
                    or raw.get('name') != ref.get('name')):
                refuse('SERIES_REFERENCE_IDENTITY_CONFLICT')
            for key in ('closePrice', 'tradeVolume'):
                value = raw.get(key)
                if not finite(value) or (value <= 0 if key == 'closePrice' else value < 0):
                    row['invalid_fields'].append(key)
                    refuse('SERIES_NUMERIC_FIELD_INVALID')
            parsed = session_day(raw.get('tradeDate'))
            if parsed is None:
                refuse('SERIES_SESSION_DATE_INVALID')
                continue
            row['date'] = parsed.isoformat()
            dates.append(parsed)
            if series_observed_day is not None and parsed > series_observed_day:
                refuse('SERIES_DATE_AFTER_RETRIEVAL')
            if ref is not None and ref_day == parsed and finite(ref.get('lasT_CP')):
                if raw.get('closePrice') != ref['lasT_CP']:
                    refuse('SAME_DATE_REFERENCE_SERIES_CLOSE_CONFLICT')
            if policy_valid:
                if not start <= parsed <= end:
                    refuse('SERIES_ROW_OUTSIDE_EXPLICIT_DATE_WINDOW')
                if parsed < guard:
                    refuse('SERIES_CROSSES_UNRESOLVED_ACTION_BOUNDARY')
        if dates and len(dates) == len(records):
            if any(a >= b for a, b in zip(dates, dates[1:])):
                refuse('SESSION_DATES_NOT_UNIQUE_CHRONOLOGICAL')
            else:
                out['series_asof'] = dates[-1].isoformat()
                if policy_valid and dates[-1] == asof:
                    out['freshness_status'] = 'MATCHES_EXPLICIT_HISTORICAL_ASOF_NOT_LATEST_SESSION'
                else:
                    refuse('SERIES_EXPECTED_ASOF_NOT_MET')
    else:
        out['inventory_issues'].append('series data array unavailable')
    if not out['reasons']:
        out['decision'] = 'STRUCTURAL_CLOSE_VOLUME_CLEAR_NOT_FINANCIAL_QUALIFICATION'
    return out
