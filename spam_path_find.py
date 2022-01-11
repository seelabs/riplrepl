#!/usr/bin/env python3

import asyncio
import argparse
from copy import deepcopy
from dataclasses import dataclass
import os
import multiprocessing as mp
import random
import time
from typing import Tuple

from app import App, single_client_app
import command
from common import Account, Asset, eprint
from config_file import ConfigFile


def parse_args_helper(parser: argparse.ArgumentParser):
    parser.add_argument(
        '--pid',
        '-p',
        help=('process id of the currently running rippled'),
    )


def parse_args():
    parser = argparse.ArgumentParser(description=('Test and debug rippled'))
    parse_args_helper(parser)
    return parser.parse_known_args()[0]


should_exit_pathfind_forever = False


def subscribe_callback(d):
    pid = os.getpid()
    eprint(f'Got callback {pid = }:\n{d}')
    global should_exit_pathfind_forever
    if 'alternatives' not in d or len(d['alternatives']) == 0:
        should_exit_pathfind_forever = True
    else:
        should_exit_pathfind_forever = False


def pathfind_forever(exe, cfg_file, candidate):

    with single_client_app(exe=exe,
                           config=ConfigFile(file_name=cfg_file),
                           run_server=False) as app:

        d = app(
            command.PathFindSubscription(src=candidate.src,
                                         dst=candidate.dst,
                                         amt=candidate.amt),
            subscribe_callback)
        pid = os.getpid()
        eprint(f'Initial pathfind connect: {pid = }:\n{d}')
        global should_exit_pathfind_forever
        while not should_exit_pathfind_forever:
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(5))


@dataclass
class PathCandidate:
    src: Account
    dst: Account
    amt: Asset
    send_max: Asset  # send_max


# list of candidates to use for path finding
# a candidate is added when a successful payment is observed from the src
# to the dst in the given currencies.
# A candidate is removed when pathfinding doesn't find any valid paths
# Key is a tuple of asserts with zero value.
# Value is the src and dst amounts to use, as well as the src and dst accounts.

payment_candidates = {}


def add_default_payment_candidate():
    src = Account(account_id='r9cZA1mLK5R5Am25ArfXFmqgNwjZgnfk59')
    dst = src
    amt = Asset(value=0.001,
                currency='USD',
                issuer=Account(account_id='rvYAfWj5gh67oV6fW32ZzP3Aw4Eubs59B'))
    src_amt = deepcopy(amt)
    src_amt.value = 1.0
    cand = PathCandidate(src, dst, amt, src_amt)
    key = (deepcopy(amt), deepcopy(src), deepcopy(dst))
    key[0].value = 0
    key[1].value = 0
    global payment_candidates
    payment_candidates[f'{key}'] = cand  # overwrite old value


add_default_payment_candidate()


def txn_subscribe_callback(d):
    try:
        if d['engine_result'] != 'tesSUCCESS' or d['transaction'][
                'TransactionType'] != 'Payment':
            return
    except:
        return

    try:
        t = d['transaction']
        src = Account(account_id=t['Account'])
        dst = Account(account_id=t['Destination'])
        amt = Asset(from_rpc_result=t['Amount'])
        send_max = None
        if 'SendMax' in t:
            send_max = Asset(from_rpc_result=t['SendMax'])
        src_amt = send_max if send_max is not None else amt
    except:
        eprint('Got exception')
        eprint(f'{t = }')
        return

    if amt.is_xrp() and src_amt.is_xrp():
        return

    try:
        # increase send max by 10%, decrease amt by 10%
        amt.value = amt.value - amt.value / 10
        src_amt.value = src_amt.value + src_amt.value / 10
        cand = PathCandidate(src, dst, amt, src_amt)
        # add it to the dictionary. Use the max for send_max, min for amt
        key = (deepcopy(amt), deepcopy(src), deepcopy(dst))
        key[0].value = 0

        global payment_candidates
        eprint(f'Adding new choice: {key}')
        payment_candidates[f'{key}'] = cand  # overwrite old value
        pid = os.getpid()
    except:
        eprint('Got exception 2')


def start_random_path_find_subscription(
        exe, cfg_file) -> Tuple[PathCandidate, mp.Process]:
    global payment_candidates
    candidate = random.choice(list(payment_candidates.values()))
    pid = os.getpid()
    eprint(
        f'Starting path find for {candidate.amt = } {len(payment_candidates) = } {pid = }'
    )
    p = mp.Process(target=pathfind_forever, args=(exe, cfg_file, candidate))
    p.start()
    return (candidate, p)

def path_find_spam(exe, cfg_file):
    with single_client_app(exe=exe,
                           config=ConfigFile(file_name=cfg_file),
                           run_server=False) as app:
        d = app(command.Subscribe(streams=['transactions']),
                txn_subscribe_callback)
        pid = os.getpid()
        eprint(f'Initial txn subscribe connect: {pid = }:\n{d}')

        # Start processes
        processes = []
        for i in range(256):
            processes.append(start_random_path_find_subscription(
                exe, cfg_file))

        # killing and restarting listeners at random
        while True:
            num_to_rm = random.randrange(16)
            # remove and start in batches; not interleaved
            for i in range(num_to_rm):
                to_rm = random.randrange(len(processes))
                processes.pop(to_rm)[1].terminate()
            for i in range(num_to_rm):
                processes.append(
                    start_random_path_find_subscription(exe, cfg_file))

            # remove any processes that have stopped
            new_processes = []
            for i, (c, p) in enumerate(processes):
                if p.is_alive():
                    new_processes.append((c, p))
                else:
                    global payment_candidates
                    key = (deepcopy(c.amt), deepcopy(c.src), deepcopy(c.dst))
                    key[0].value = 0
                    key[1].value = 0
                    eprint(f'xxx Rm choice: {key}')
                    payment_candidates.pop(f'{key}', None)
                    new_processes.append(
                        start_random_path_find_subscription(exe, cfg_file))
            processes = new_processes
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(2))


def main():
    # the default method is 'fork'
    # but if we fork the websock ends up being shared in the
    # child processes
    mp.set_start_method('spawn')
    args = parse_args()
    if not args.pid:
        raise ValueError(
            "Must specify process id of currently running rippled")
    pid = args.pid
    if not os.path.exists(f'/proc/{pid}'):
        raise ValueError(f'Process {pid} does not have a /proc entry')
    if not os.path.exists(f'/proc/{pid}/exe'):
        raise ValueError(f'Process {pid} does not have an exe entry')
    exe = f'/proc/{pid}/exe'

    cmdline_file = f'/proc/{pid}/cmdline'
    if not os.path.exists(cmdline_file):
        raise ValueError(f'Process {pid} does not have a cmdline entry')

    cfg_file = None

    with open(cmdline_file) as f:
        for l in f:
            if l:
                use_next = False
                for w in l.split('\0'):
                    if use_next:
                        cfg_file = w
                        break
                    if w == '--conf':
                        use_next = True

    if cfg_file is None:
        raise ValueError('Could not determine config file from command line')

    if not os.path.exists(cfg_file):
        raise ValueError(f'Config file: {cfg_file} does not exist')

    path_find_spam(exe, cfg_file)


if __name__ == '__main__':
    main()
