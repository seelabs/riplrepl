#!/usr/bin/env python3

import argparse
import json
from typing import Optional, Tuple

from app import App, single_client_app
import command
from common import Account, Asset, eprint


def parse_args_helper(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--server",
        "-s",
        # should be of the form: f'{protocol}://{ip}:{port}'
        help=("address and port of the server to connect to"),
    )
    parser.add_argument(
        "--begin", "-b", help=("Sequence number of beginning of search range.")
    )
    parser.add_argument(
        "--end", "-e", help=("Sequence number of ending of search range.")
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Find first transaction that cuases a negative spread in an offer book"
        )
    )
    parse_args_helper(parser)
    return parser.parse_known_args()[0]


def best_offer(
    app, taker_pays, taker_gets, ledger_index
) -> Tuple[Optional[dict], Optional[int]]:
    r = app(
        command.BookOffers(
            taker_pays=taker_pays, taker_gets=taker_gets, ledger_index=ledger_index
        )
    )
    if "offers" not in r or len(r["offers"]) == 0 or "ledger_index" not in r:
        return (None, None)
    return (r["offers"][0], r["ledger_index"])


def rate(offer_dict):
    taker_pays = Asset(from_rpc_result=offer_dict["TakerPays"])
    taker_gets = Asset(from_rpc_result=offer_dict["TakerGets"])
    return float(taker_pays.value) / float(taker_gets.value)


smallest_spread = 10000000
largest_spread = 0
last_spread = 1000000


def is_neg_spread(o1, o2, cur_index):
    rate1 = rate(o1)
    rate2 = rate(o2)
    inv_rate1 = 1 / rate1
    spread = rate2 - inv_rate1
    global smallest_spread
    global largest_spread
    global last_spread
    if spread < smallest_spread:
        smallest_spread = spread
        eprint(f"{smallest_spread=} {cur_index=}")
    if spread > largest_spread:
        largest_spread = spread
        eprint(f"{largest_spread=} {cur_index=}")
    neg_spread = inv_rate1 > rate2
    if neg_spread and last_spread != spread:
        inv_rate2 = 1 / rate2
        eprint(f"{rate1=} {rate2=} {inv_rate1=} {inv_rate2=} {cur_index=}")
        eprint(f"\n{o1=}\n{o2=}\n")
    last_spread = spread
    return neg_spread


def main():
    args = parse_args()
    websocket_uri = "wss://s1.ripple.com"
    if args.server:
        websocket_uri = args.server

    begin_range = 69168977  # Closed on: Jan 21, 2022, 09:39:41 PM UTC
    end_range = 69197759  # Closed on: Jan 23, 2022, 05:20:12 AM UTC
    if args.begin:
        begin_range = int(args.begin)
    if args.end:
        end_range = int(args.begin)

    eprint(f"{begin_range=} {end_range=}")

    issuer = Account(account_id="rctArjqVvTHihekzDeecKo6mkTYTUSBNc")
    asset1 = Asset(currency="XRP")
    asset2 = Asset(issuer=issuer, currency="SGB")
    with single_client_app(websocket_uri=websocket_uri, run_server=False) as app:
        cur_index = end_range
        for i, cur_index in enumerate(range(begin_range, end_range)):
            if (i % 100) == 0:
                eprint(f"{i=} {cur_index=}")
            b1, ledger_index1 = best_offer(app, asset1, asset2, cur_index)
            b2, ledger_index2 = best_offer(app, asset2, asset1, cur_index)
            assert ledger_index1 == cur_index and ledger_index2 == cur_index
            if b1 and b2:
                if ledger_index1 != ledger_index2:
                    eprint(f"Mismatched ledger indexes: {ledger_index1=} {cur_index=}")
                elif is_neg_spread(b1, b2, cur_index):
                    eprint(f"Found negative spread: {last_spread=} {cur_index=}")
            else:
                eprint(f"No best offer: {cur_index=}")


if __name__ == "__main__":
    main()
