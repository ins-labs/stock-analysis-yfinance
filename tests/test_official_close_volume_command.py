"""Invented-only private command wiring fixtures. SOURCE / UNRUN, no requests."""
import contextlib
from email.message import Message
import hashlib
from http.client import BadStatusLine, IncompleteRead, RemoteDisconnected
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import official_close_volume_command as command
from command_runner import parse_command


EVIDENCE = b'Invented historical policy evidence. Not a provider record or grant.'


class FakeResponse:
    def __init__(self, url, body, status=200, final_url=None, content_type='application/json'):
        self.url = url
        self.final_url = url if final_url is None else final_url
        self.body = body
        self.status = status
        self.headers = Message()
        self.headers['Content-Type'] = content_type
        self.read_bounds = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.final_url

    def read(self, size):
        self.read_bounds.append(size)
        return self.body[:size]


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request):
        self.requests.append(request)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class OfficialCommandTests(unittest.TestCase):
    def policy(self):
        return {'requested_isin': 'INVENTED001', 'requested_symbol': 'EXAMPLE.CA', 'requested_days': 30,
                'window_start': '2020-02-02', 'window_end': '2020-02-03', 'expected_asof': '2020-02-03',
                'admissible_since': '2020-02-01', 'policy_source_url': 'https://evidence.example/notice',
                'policy_evidence_sha256': hashlib.sha256(EVIDENCE).hexdigest()}

    def bodies(self):
        reference = {'success': True, 'totalCount': 1, 'data': [{
            'isin': 'INVENTED001', 'reuters': 'EXAMPLE.CA', 'name': 'Example Equity',
            'schedule': 'Egyptian securities-Stocks', 'curr': 'L.E', 'curR_LONG': 'Egyptian Pound',
            'lasT_TRADE_DATE': '2020-02-02T00:00:00', 'lasT_CP': 12.0}]}
        series = {'success': True, 'totalCount': 2, 'data': [
            {'isinCode': 'INVENTED001', 'name': 'Example Equity', 'tradeDate': '2020-02-02T00:00:00',
             'closePrice': 12.0, 'tradeVolume': 0},
            {'isinCode': 'INVENTED001', 'name': 'Example Equity', 'tradeDate': '2020-02-03T00:00:00',
             'closePrice': 13.0, 'tradeVolume': 2}]}
        return reference, series

    def opener(self, reference=None, series=None):
        default_reference, default_series = self.bodies()
        reference = default_reference if reference is None else reference
        series = default_series if series is None else series
        return FakeOpener([
            FakeResponse(command.BASE + 'stock-info?Isin=INVENTED001', json.dumps(reference).encode()),
            FakeResponse(command.BASE + 'price-volume-points?isin=INVENTED001&date=30', json.dumps(series).encode())])

    def enabled(self, policy, output, opener, evidence=EVIDENCE):
        with patch.object(command, 'OFFICIAL_PRIVATE_COMMAND_ENABLED', True), patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}):
            return command.run_private(policy, output, policy_evidence_bytes=evidence, opener=opener)

    def test_explicit_disabled_fallback_before_network_or_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'private'
            opener = self.opener()
            with patch.object(command, 'OFFICIAL_PRIVATE_COMMAND_ENABLED', False):
                result = command.run_private(self.policy(), target, policy_evidence_bytes=EVIDENCE, opener=opener)
            self.assertEqual(result, {'rc': 2, 'status': 'DISABLED_NO_REQUEST'})
            self.assertEqual(opener.requests, [])
            self.assertFalse(target.exists())

    def test_public_actions_refused_even_if_enablement_constant_changed(self):
        opener = self.opener()
        with patch.object(command, 'OFFICIAL_PRIVATE_COMMAND_ENABLED', True), patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            result = command.run_private(self.policy(), '/unused', policy_evidence_bytes=EVIDENCE, opener=opener)
        self.assertEqual(result['rc'], 2)
        self.assertEqual(opener.requests, [])

    def test_success_private_complete_originals_reference_join_and_receipts(self):
        opener = self.opener()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'private'
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                result = self.enabled(self.policy(), target, opener)
            self.assertEqual(result, {'rc': 0, 'status': 'PRIVATE_STRUCTURAL_ASSESSMENT_ONLY'})
            self.assertEqual(stream.getvalue(), '')
            report = json.loads((target / 'assessment.private.json').read_bytes())
            self.assertEqual(report['row_count'], 2)
            self.assertEqual(report['series_asof'], '2020-02-03')
            self.assertFalse(report['current_quote_usable'])
            self.assertEqual(report['currency'], 'EGP')
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            for record in json.loads((target / 'manifest.private.json').read_bytes()):
                raw = (target / record['name']).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), record['sha256'])
                self.assertEqual(len(raw), record['bytes'])
                self.assertEqual((target / record['name']).stat().st_mode & 0o777, 0o600)
            for prefix in ('reference', 'series'):
                raw = (target / (prefix + '.body.private.json')).read_bytes()
                receipt = json.loads((target / (prefix + '.receipt.private.json')).read_bytes())
                self.assertEqual(receipt['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(receipt['bytes'], len(raw))
                self.assertTrue(receipt['retrieved_utc'].endswith('+00:00'))
                self.assertNotIn('headers', receipt)

    def test_exact_two_gets_fixed_public_headers_no_auth_or_cookie(self):
        opener = self.opener()
        with tempfile.TemporaryDirectory() as temp:
            self.enabled(self.policy(), Path(temp) / 'private', opener)
        self.assertEqual(len(opener.requests), 2)
        self.assertEqual([r.get_method() for r in opener.requests], ['GET', 'GET'])
        self.assertEqual([r.full_url for r in opener.requests], [
            command.BASE + 'stock-info?Isin=INVENTED001',
            command.BASE + 'price-volume-points?isin=INVENTED001&date=30'])
        for request in opener.requests:
            headers = {k.lower(): v for k, v in request.header_items()}
            self.assertEqual(headers['x-egx-bff-request'], '1')
            self.assertEqual(headers['x-egx-bff-client'], 'web')
            self.assertNotIn('authorization', headers)
            self.assertNotIn('cookie', headers)

    def test_partial_null_or_identity_failure_no_success_or_row_drop(self):
        for key, value in [('closePrice', None), ('tradeVolume', -1), ('isinCode', 'OTHER')]:
            reference, series = self.bodies()
            series['data'][0][key] = value
            opener = self.opener(reference, series)
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / 'private'
                result = self.enabled(self.policy(), target, opener)
                self.assertEqual(result['rc'], 1)
                self.assertEqual(result['status'], 'PRIVATE_ASSESSMENT_REFUSED')
                report = json.loads((target / 'assessment.private.json').read_bytes())
                self.assertEqual(report['row_count'], 2)
                self.assertEqual(report['rows'][0]['raw'][key], value)

    def test_new_asof_never_inherits_previous_historical_clear(self):
        policy = self.policy()
        policy.update(window_end='2020-02-04', expected_asof='2020-02-04')
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'private'
            result = self.enabled(policy, target, self.opener())
            self.assertEqual(result['rc'], 1)
            report = json.loads((target / 'assessment.private.json').read_bytes())
            self.assertIn('SERIES_EXPECTED_ASOF_NOT_MET', report['reasons'])
            self.assertEqual(report['row_count'], 2)

    def test_deny_throttle_and_network_errors_single_attempt_no_retry(self):
        url = command.BASE + 'stock-info?Isin=INVENTED001'
        for error in (HTTPError(url, 403, 'forbidden', {}, None), HTTPError(url, 429, 'limited', {}, None),
                      URLError('private text not printed')):
            opener = FakeOpener([error])
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / 'private'
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    result = self.enabled(self.policy(), target, opener)
                self.assertEqual(result['rc'], 1)
                self.assertEqual(len(opener.requests), 1)
                self.assertEqual(stream.getvalue(), '')
                self.assertTrue((target / 'failure.private.json').exists())
                self.assertFalse((target / 'assessment.private.json').exists())

    def test_second_request_failure_retains_first_original_privately(self):
        opener = self.opener()
        opener.responses[1] = URLError('not a successful dataset')
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'private'
            result = self.enabled(self.policy(), target, opener)
            self.assertEqual(result['rc'], 1)
            self.assertEqual(len(opener.requests), 2)
            self.assertTrue((target / 'reference.body.private.json').exists())
            self.assertFalse((target / 'assessment.private.json').exists())
            self.assertTrue((target / 'failure.private.json').exists())

    def test_redirect_status_content_type_and_oversize_refused(self):
        url = command.BASE + 'stock-info?Isin=INVENTED001'
        responses = [FakeResponse(url, b'{}', status=404),
                     FakeResponse(url, b'{}', final_url='https://elsewhere.example'),
                     FakeResponse(url, b'html', content_type='text/html'),
                     FakeResponse(url, b'x' * (command.MAX_RESPONSE_BYTES + 1))]
        for response in responses:
            opener = FakeOpener([response])
            with tempfile.TemporaryDirectory() as temp:
                self.assertEqual(self.enabled(self.policy(), Path(temp) / 'private', opener)['rc'], 1)
                self.assertEqual(len(opener.requests), 1)
        with self.assertRaises(ValueError):
            command.RefuseRedirect().redirect_request(None, None, 302, None, None, 'https://elsewhere.example')

    def test_existing_output_directory_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'private'
            target.mkdir()
            (target / 'other-work').write_text('keep')
            opener = self.opener()
            self.assertEqual(self.enabled(self.policy(), target, opener)['rc'], 1)
            self.assertEqual(opener.requests, [])
            self.assertEqual((target / 'other-work').read_text(), 'keep')
            self.assertFalse((target / 'failure.private.json').exists())

    def test_policy_evidence_mismatch_before_output_or_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'private'
            opener = self.opener()
            result = self.enabled(self.policy(), target, opener, evidence=b'other')
            self.assertEqual(result['rc'], 1)
            self.assertEqual(opener.requests, [])
            self.assertFalse(target.exists())

    def test_exact_policy_schema_identity_and_date_scope_fail_before_requests(self):
        mutations = [{'requested_days': True}, {'requested_days': 31}, {'requested_isin': '../../x'},
                     {'requested_symbol': 'EXAMPLE;bad'}, {'window_start': '2020-02-30'},
                     {'expected_asof': None}, {'admissible_since': '2020-02-04'},
                     {'policy_source_url': 'http://evidence.example'}, {'policy_evidence_sha256': ''},
                     {'unexpected': 'not accepted'}]
        for mutation in mutations:
            policy = self.policy()
            policy.update(mutation)
            with tempfile.TemporaryDirectory() as temp:
                opener = self.opener()
                self.assertEqual(self.enabled(policy, Path(temp) / 'private', opener)['rc'], 1)
                self.assertEqual(opener.requests, [])
        policy = self.policy()
        del policy['expected_asof']
        with self.assertRaises(ValueError):
            command.validate_policy(policy)

    def test_relative_output_path_is_not_used(self):
        opener = self.opener()
        self.assertEqual(self.enabled(self.policy(), 'relative-output', opener)['rc'], 1)
        self.assertEqual(opener.requests, [])

    def test_explicit_disabled_cli_does_not_read_nonexistent_policy_or_print_private_arguments(self):
        stream = io.StringIO()
        with patch.object(command, 'OFFICIAL_PRIVATE_COMMAND_ENABLED', False), contextlib.redirect_stdout(stream):
            rc = command.main(['--policy-file', '/nonexistent-policy', '--policy-evidence-file', '/nonexistent-evidence',
                               '--private-output-directory', '/unused-private'])
        self.assertEqual(rc, 2)
        self.assertEqual(stream.getvalue(), 'OFFICIAL_PRIVATE_COMMAND_DISABLED_NO_REQUEST\n')
        self.assertNotIn('nonexistent', stream.getvalue())

    def test_public_dispatcher_stays_fixed_fixture_only(self):
        self.assertTrue(parse_command('python fixture_demo.py'))
        with self.assertRaises(ValueError):
            parse_command('python official_close_volume_command.py --policy-file private.json')

    def test_duplicate_policy_keys_are_not_silently_selected(self):
        with self.assertRaises(ValueError):
            command.load_policy_bytes(b'{"expected_asof":"2020-02-03","expected_asof":"2020-02-04"}')

    def test_source_and_runtime_binding_written_privately(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'private'
            self.assertEqual(self.enabled(self.policy(), target, self.opener())['rc'], 0)
            binding = json.loads((target / 'execution.private.json').read_bytes())
            self.assertEqual(binding['command_source_sha256'], hashlib.sha256(Path(command.__file__).read_bytes()).hexdigest())
            self.assertEqual(binding['adapter_source_sha256'], hashlib.sha256((Path(command.__file__).parent / 'egx_close_volume_admission.py').read_bytes()).hexdigest())
            self.assertIn('python', binding)

    def test_default_network_builder_disables_environment_proxy_and_redirects(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(command, 'OFFICIAL_PRIVATE_COMMAND_ENABLED', True), \
                patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), patch.object(command, 'build_opener', return_value=self.opener()) as build:
            result = command.run_private(self.policy(), Path(temp) / 'private', policy_evidence_bytes=EVIDENCE)
            self.assertEqual(result['rc'], 0)
            self.assertIsInstance(build.call_args.args[0], command.ProxyHandler)
            self.assertEqual(build.call_args.args[0].proxies, {})
            self.assertIsInstance(build.call_args.args[1], command.RefuseRedirect)

    def test_protocol_open_errors_fixed_refusal_without_provider_text_or_retry(self):
        sentinel = 'PRIVATE-PROVIDER-PROTOCOL-SENTINEL'
        for error in (IncompleteRead(sentinel.encode()), BadStatusLine(sentinel), RemoteDisconnected(sentinel)):
            opener = FakeOpener([error])
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / 'private'
                stdout, stderr = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = self.enabled(self.policy(), target, opener)
                self.assertEqual(result, {'rc': 1, 'status': 'PRIVATE_COMMAND_REFUSED_OR_INCOMPLETE'})
                self.assertEqual(len(opener.requests), 1)
                self.assertTrue((target / 'failure.private.json').exists())
                self.assertFalse((target / 'assessment.private.json').exists())
                self.assertNotIn(sentinel, stdout.getvalue() + stderr.getvalue())
                self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')
                self.assertNotIn(sentinel, (target / 'failure.private.json').read_text())

    def test_protocol_read_errors_first_and_second_fetch_preserve_available_originals(self):
        sentinel = 'PRIVATE-READ-PROTOCOL-SENTINEL'
        class ReadFailure(FakeResponse):
            def __init__(self, response, error):
                super().__init__(response.url, response.body)
                self.error = error
            def read(self, size):
                raise self.error
        for position in (0, 1):
            for error in (IncompleteRead(sentinel.encode()), BadStatusLine(sentinel)):
                opener = self.opener()
                opener.responses[position] = ReadFailure(opener.responses[position], error)
                with tempfile.TemporaryDirectory() as temp:
                    target = Path(temp) / 'private'
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        result = self.enabled(self.policy(), target, opener)
                    self.assertEqual(result['rc'], 1)
                    self.assertEqual(len(opener.requests), position + 1)
                    self.assertTrue((target / 'failure.private.json').exists())
                    self.assertFalse((target / 'assessment.private.json').exists())
                    self.assertEqual((target / 'reference.body.private.json').exists(), position == 1)
                    self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')
                    self.assertNotIn(sentinel, (target / 'failure.private.json').read_text())

    def test_second_fetch_protocol_open_failure_keeps_first_complete_original(self):
        opener = self.opener()
        opener.responses[1] = BadStatusLine('PRIVATE-SECOND-OPEN-SENTINEL')
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'private'
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = self.enabled(self.policy(), target, opener)
            self.assertEqual(result['rc'], 1)
            self.assertEqual(len(opener.requests), 2)
            self.assertTrue((target / 'reference.body.private.json').exists())
            self.assertTrue((target / 'reference.receipt.private.json').exists())
            self.assertTrue((target / 'failure.private.json').exists())
            self.assertEqual(stdout.getvalue() + stderr.getvalue(), '')

    def test_enabled_malformed_cli_arguments_never_echo_private_argv(self):
        sentinel = 'PRIVATE-ARGUMENT-SENTINEL'
        cases = [[], ['--unknown', sentinel], ['--policy-file'],
                 ['--policy-file', sentinel, '--policy-evidence-file', sentinel,
                  '--private-output-directory', sentinel, '--unknown=' + sentinel]]
        for argv in cases:
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(command, 'OFFICIAL_PRIVATE_COMMAND_ENABLED', True), \
                    patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), \
                    patch.object(command.Path, 'read_bytes', side_effect=AssertionError('must not read')), \
                    patch.object(command, 'build_opener', side_effect=AssertionError('must not request')), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = command.main(argv)
            self.assertEqual(rc, 1)
            self.assertEqual(stdout.getvalue(), 'PRIVATE_INPUT_REFUSED\n')
            self.assertEqual(stderr.getvalue(), '')
            self.assertNotIn(sentinel, stdout.getvalue() + stderr.getvalue())

    def test_enabled_default_cli_reads_private_policy_and_runs_exact_two_mock_gets(self):
        self.assertIs(command.OFFICIAL_PRIVATE_COMMAND_ENABLED, True)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = root / 'caller-policy.private.json'
            evidence = root / 'evidence.private'
            policy.write_text(json.dumps(self.policy()))
            evidence.write_bytes(EVIDENCE)
            output = root / 'private-result'
            opener = self.opener()
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), \
                    patch.object(command, 'build_opener', return_value=opener), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                rc = command.main(['--policy-file', str(policy), '--policy-evidence-file', str(evidence),
                                   '--private-output-directory', str(output)])
            self.assertEqual(rc, 0)
            self.assertEqual(len(opener.requests), 2)
            self.assertEqual(stdout.getvalue(), 'PRIVATE_STRUCTURAL_ASSESSMENT_ONLY\n')
            self.assertEqual(stderr.getvalue(), '')
            self.assertTrue((output / 'manifest.private.json').exists())
            report = json.loads((output / 'assessment.private.json').read_bytes())
            self.assertEqual(report['row_count'], 2)
            self.assertFalse(report['current_quote_usable'])

    def test_enabled_default_cli_actions_refuses_before_inputs_and_network(self):
        self.assertIs(command.OFFICIAL_PRIVATE_COMMAND_ENABLED, True)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), \
                patch.object(command.Path, 'read_bytes', side_effect=AssertionError('no input read')), \
                patch.object(command, 'build_opener', side_effect=AssertionError('no request')), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = command.main(['--private-sentinel=not-echoed'])
        self.assertEqual(rc, 2)
        self.assertEqual(stdout.getvalue(), 'PUBLIC_ACTIONS_VENUE_REFUSED_NO_REQUEST\n')
        self.assertEqual(stderr.getvalue(), '')

    def test_enabled_default_cli_does_not_expand_public_persistent_dispatcher(self):
        self.assertIs(command.OFFICIAL_PRIVATE_COMMAND_ENABLED, True)
        with self.assertRaises(ValueError):
            parse_command('python official_close_volume_command.py --policy-file private.json')
        self.assertTrue(parse_command('python fixture_demo.py'))


if __name__ == '__main__':
    unittest.main()
