#!/usr/bin/env python3

import sys
import re
from collections import defaultdict


def main():
    ignore_messages = []
    ignore_file = None
    if len(sys.argv) > 1:
        ignore_file = sys.argv[1]
        with open(ignore_file) as f:
            ignore_messages = f.readlines()

    messages = defaultdict(lambda: defaultdict(set))
    for line in sys.stdin:
        match = re.match(r'^(.+?):(\d+): (.+)$', line)
        if not match or any(ignore in line for ignore in ignore_messages):
            continue
        path, lineno, message = match.groups()
        messages[message][path].add(int(lineno))

    if sys.argv[2:3] == ['ok']:
        with open(ignore_file, 'a') as f:
            for message in sorted(messages):
                f.write(message + '\n')
        print('Added', len(messages), 'messages to', ignore_file)
    else:
        for message, places in sorted(messages.items()):
            print(message)
            for path, linenos in sorted(places.items()):
                print(' ', path, ':', ', '.join(map(str, sorted(linenos))))
            print()


main()
