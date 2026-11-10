"""SOURCE ONLY / UNRUN. Execute on approved public CI, not during authoring."""
import argparse
import unittest
from unittest.mock import patch
import analysis
import command_runner


class PublicCommandTests(unittest.TestCase):
    def test_ticker_validation(self):
        self.assertEqual(analysis.ticker_list('poul.ca,MSFT,poul.ca'), ['POUL.CA', 'MSFT'])
        for text in ('', '../private', 'X;echo', 'A/B', 'A\nB'):
            with self.subTest(text=text), self.assertRaises(argparse.ArgumentTypeError):
                analysis.ticker_list(text)

    def test_persistent_command_argv(self):
        args = command_runner.parse_command('python fixture_demo.py')
        self.assertEqual(args[1:], ['fixture_demo.py'])

    def test_real_market_command_is_disabled(self):
        with self.assertRaises(ValueError):
            command_runner.parse_command('python analysis.py --tickers POUL.CA --period 1y')

    def test_no_shell_or_arbitrary_program(self):
        for value in ('sh -c echo', 'python analysis.py --tickers X --period 1y;id',
                      'python other.py --tickers X --period 1y', '',
                      'python analysis.py --tickers ../x --period 1y'):
            with self.subTest(value=value), self.assertRaises((ValueError, argparse.ArgumentTypeError)):
                command_runner.parse_command(value)

    def test_child_failure_retained(self):
        with patch.dict('os.environ', {'ANALYSIS_COMMAND': 'python fixture_demo.py'}), patch('command_runner.subprocess.run') as run:
            run.return_value.returncode = 7
            self.assertEqual(command_runner.main(), 7)
            self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_empty_data_fails(self):
        import pandas as pd
        with self.assertRaises(ValueError):
            analysis.summarize(pd.DataFrame({'Close': []}))

    def test_summary_is_adjusted_price_not_total_return(self):
        import pandas as pd
        frame = pd.DataFrame({'Close': [10.0, 12.0], 'Dividends': [0.0, 0.5]},
                             index=pd.to_datetime(['2026-01-01', '2026-01-02']))
        result = analysis.summarize(frame)
        self.assertAlmostEqual(result['adjusted_price_change_pct'], 20.0)
        self.assertEqual(result['dividends_in_returned_window'], 0.5)
        self.assertEqual(result['rows'], 2)


if __name__ == '__main__':
    unittest.main()
