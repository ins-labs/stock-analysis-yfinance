# SPDX-License-Identifier: CC0-1.0
"""Invented, openly licensed plumbing fixture. No Yahoo or real ticker data."""
import json


def main():
    prices = [10.0, 12.0]
    print(json.dumps({'data_kind': 'SYNTHETIC_FIXTURE_ONLY',
                      'real_market_data': False,
                      'fixture_id': 'invented-two-price-example',
                      'invented_prices': prices,
                      'invented_change_pct': (prices[-1] / prices[0] - 1) * 100,
                      'license': 'CC0-1.0',
                      'notice': 'Plumbing proof only. Not POUL.CA analysis or market evidence.'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
