#!/usr/bin/env python3

import asyncio
import argparse
import os
import multiprocessing as mp
import random
import time

from app import App, single_client_app
import command
from common import Account, Asset
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


callback_count = 0


def subscribe_callback(d):
    global callback_count
    callback_count = callback_count + 1
    pid = os.getpid()
    if not callback_count % 10:
        print(f'Got callback {pid = }:\n {d}')
    else:
        print(f'Got callback {pid = }\n')


def subscribe_forever(exe, cfg_file):
    with single_client_app(exe=exe,
                           config=ConfigFile(file_name=cfg_file),
                           run_server=False) as app:
        account = Account(account_id='r9cZA1mLK5R5Am25ArfXFmqgNwjZgnfk59')
        issuer = Account(account_id='rvYAfWj5gh67oV6fW32ZzP3Aw4Eubs59B')
        amt = Asset(value=0.001, currency='USD', issuer=issuer)
        si = app(
            command.PathFindSubscription(src=account, dst=account, amt=amt),
            subscribe_callback)
        # print(f'{si = }')
        while True:
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(60))
            print(f'Done sleeping')


def main():
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

    # Start processes
    processes = []
    for i in range(256):
        p = mp.Process(target=subscribe_forever, args=(exe, cfg_file))
        p.start()
        processes.append(p)

    # killing and restarting listeners at random
    while True:
        num_to_rm = random.randrange(16)
        # remove and start in batches; not interleaved
        for i in range(num_to_rm):
            to_rm = random.randrange(len(processes))
            processes.pop(to_rm).terminate()
        for i in range(num_to_rm):
            p = mp.Process(target=subscribe_forever, args=(exe, cfg_file))
            p.start()
            processes.append(p)
        time.sleep(2)


if __name__ == '__main__':
    main()
