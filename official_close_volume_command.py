"""Private official EGX historical close-volume command.

The public persistent dispatcher remains fixture-only. This module never prints
market rows, receipts, symbols, URLs, exceptions or descriptive metrics. It remains excluded
from the public dispatcher; private venue and caller policy need grounded scope.
"""
import argparse
from datetime import date, datetime, timezone
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from egx_close_volume_admission import assess_egx_close_volume


OFFICIAL_PRIVATE_COMMAND_ENABLED = True
MAX_RESPONSE_BYTES = 5_000_000
BASE = 'https://beta.egx.com.eg/api/bff/egx/'
POLICY_KEYS = {'requested_isin', 'requested_symbol', 'requested_days',
               'window_start', 'window_end', 'expected_asof', 'admissible_since',
               'policy_source_url', 'policy_evidence_sha256'}


class RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, newurl):
        raise ValueError('redirect refused')


def validate_policy(policy):
    """Validate explicit parameters, not the authority/authorship of evidence."""
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise ValueError('exact explicit policy required')
    if not isinstance(policy['requested_isin'], str) or not re.fullmatch(r'[A-Z0-9]{6,24}', policy['requested_isin']):
        raise ValueError('invalid ISIN label')
    if not isinstance(policy['requested_symbol'], str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9.=-]{0,31}', policy['requested_symbol']):
        raise ValueError('invalid exact symbol')
    if type(policy['requested_days']) is not int or policy['requested_days'] not in (30, 60, 180, 365, 730, 1095):
        raise ValueError('unsupported source range selector')
    values = []
    for key in ('window_start', 'window_end', 'expected_asof', 'admissible_since'):
        raw = policy[key]
        if not isinstance(raw, str):
            raise ValueError('explicit date required')
        parsed = date.fromisoformat(raw)
        if parsed.isoformat() != raw:
            raise ValueError('canonical date required')
        values.append(parsed)
    start, end, asof, guard = values
    if not guard <= start <= asof <= end:
        raise ValueError('inconsistent historical date scope')
    url = policy['policy_source_url']
    if not isinstance(url, str) or not url.startswith('https://') or url != url.strip():
        raise ValueError('policy evidence URL required')
    digest = policy['policy_evidence_sha256']
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('policy evidence bytes digest required')
    return dict(policy)


def private_write(directory, name, raw):
    # Fixed internal filenames only, new files only, no symlink replacement.
    target = directory / name
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(raw)
    return {'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode()


def get_original(opener, endpoint):
    """One ordinary owning-site GET, bounded body, no auth/cookies/retry/fallback."""
    request = Request(endpoint, method='GET', headers={
        'Accept': 'application/json', 'x-egx-bff-request': '1', 'x-egx-bff-client': 'web'})
    with opener.open(request) as response:
        if response.status != 200 or response.geturl() != endpoint:
            raise ValueError('status or final endpoint conflict')
        if response.headers.get_content_type() != 'application/json':
            raise ValueError('unexpected response content type')
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('response exceeds private bound')
        receipt = {'url': endpoint, 'final_url': response.geturl(), 'status': response.status,
                   'retrieved_utc': datetime.now(timezone.utc).isoformat(),
                   'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        # Set-Cookie and arbitrary response headers are intentionally not retained.
    return raw, receipt


def run_private(policy, output_directory, *, policy_evidence_bytes, opener=None):
    """Private service entry, excluded from public Actions and the fixture dispatcher.

    The caller must independently ground the evidence's authorship, audience and
    policy scope. A digest match is custody only, never a new grant or factor.
    Existing directories are refused rather than overwriting another workload.
    No response is dropped, repaired, spliced or printed, even on refusal.
    """
    if not OFFICIAL_PRIVATE_COMMAND_ENABLED:
        return {'rc': 2, 'status': 'DISABLED_NO_REQUEST'}
    if os.environ.get('GITHUB_ACTIONS', '').lower() == 'true':
        return {'rc': 2, 'status': 'PUBLIC_ACTIONS_VENUE_REFUSED_NO_REQUEST'}
    directory = None
    try:
        checked = validate_policy(policy)
        if (not isinstance(policy_evidence_bytes, bytes)
                or hashlib.sha256(policy_evidence_bytes).hexdigest() != checked['policy_evidence_sha256']):
            raise ValueError('policy evidence custody conflict')
        target = Path(output_directory)
        if not target.is_absolute():
            raise ValueError('private absolute output directory required')
        target.mkdir(mode=0o700, parents=False, exist_ok=False)
        directory = target
        # No reusable connection, cookies, credential handler or alternate host.
        network = opener if opener is not None else build_opener(ProxyHandler({}), RefuseRedirect())
        manifest = []
        source_binding = {'python': sys.version, 'executable': sys.executable,
                          'command_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          'adapter_source_sha256': hashlib.sha256((Path(__file__).parent / 'egx_close_volume_admission.py').read_bytes()).hexdigest(),
                          'scope': 'PRIVATE_HISTORICAL_CLOSE_VOLUME_NOT_FINANCIAL_QUALIFICATION'}
        manifest.append(private_write(directory, 'execution.private.json', json_bytes(source_binding)))
        manifest.append(private_write(directory, 'policy.private.json', json_bytes(checked)))
        manifest.append(private_write(directory, 'policy-evidence.private', policy_evidence_bytes))
        args = {key: checked[key] for key in POLICY_KEYS if key != 'policy_evidence_sha256'}
        series_url = BASE + 'price-volume-points?' + urlencode({
            'isin': checked['requested_isin'], 'date': checked['requested_days']})
        reference_url = BASE + 'stock-info?' + urlencode({'Isin': checked['requested_isin']})
        reference, reference_receipt = get_original(network, reference_url)
        manifest.append(private_write(directory, 'reference.body.private.json', reference))
        manifest.append(private_write(directory, 'reference.receipt.private.json', json_bytes(reference_receipt)))
        series, series_receipt = get_original(network, series_url)
        manifest.append(private_write(directory, 'series.body.private.json', series))
        manifest.append(private_write(directory, 'series.receipt.private.json', json_bytes(series_receipt)))
        result = assess_egx_close_volume(series, reference, series_receipt=series_receipt,
                                         reference_receipt=reference_receipt, **args)
        manifest.append(private_write(directory, 'assessment.private.json', json_bytes(result)))
        private_write(directory, 'manifest.private.json', json_bytes(manifest))
        if result['decision'] != 'STRUCTURAL_CLOSE_VOLUME_CLEAR_NOT_FINANCIAL_QUALIFICATION':
            return {'rc': 1, 'status': 'PRIVATE_ASSESSMENT_REFUSED'}
        return {'rc': 0, 'status': 'PRIVATE_STRUCTURAL_ASSESSMENT_ONLY'}
    except (OSError, ValueError, TypeError, KeyError, HTTPError, URLError, HTTPException):
        # Do not echo exception strings, URLs, source data or private paths.
        if directory is not None:
            try:
                private_write(directory, 'failure.private.json', json_bytes({
                    'status': 'REFUSED_OR_INCOMPLETE', 'complete_assessment': False,
                    'notice': 'Previously written originals retained privately, never treated as a passed series.'}))
            except OSError:
                pass
        return {'rc': 1, 'status': 'PRIVATE_COMMAND_REFUSED_OR_INCOMPLETE'}


def load_policy_bytes(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate policy key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse errors may embed argv values. Never echo them.
        raise ValueError('private command arguments refused')


def main(argv=None):
    # Do not parse/echo private argv or read inputs while the entry is disabled.
    if not OFFICIAL_PRIVATE_COMMAND_ENABLED:
        print('OFFICIAL_PRIVATE_COMMAND_DISABLED_NO_REQUEST')
        return 2
    if os.environ.get('GITHUB_ACTIONS', '').lower() == 'true':
        print('PUBLIC_ACTIONS_VENUE_REFUSED_NO_REQUEST')
        return 2
    parser = PrivateArgumentParser(description='Private historical close-volume command')
    parser.add_argument('--policy-file', required=True)
    parser.add_argument('--policy-evidence-file', required=True)
    parser.add_argument('--private-output-directory', required=True)
    try:
        args = parser.parse_args(argv)
        policy = load_policy_bytes(Path(args.policy_file).read_bytes())
        evidence = Path(args.policy_evidence_file).read_bytes()
        outcome = run_private(policy, args.private_output_directory, policy_evidence_bytes=evidence)
    except (OSError, ValueError, TypeError):
        outcome = {'rc': 1, 'status': 'PRIVATE_INPUT_REFUSED'}
    print(outcome['status'])
    return outcome['rc']


if __name__ == '__main__':
    raise SystemExit(main())
