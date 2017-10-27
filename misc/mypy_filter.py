#!/usr/bin/env python3

"""
This script parses output from mypy and makes it more manageable, particularly
if lots of warnings are raised that you want to ignore. It's an alternative to
'# type: ignore' comments and other ways of appeasing mypy that doesn't
interfere with your source code.

Here is how to use it in this project:

python3 -m mypy -p birdseye --ignore-missing-imports | misc/mypy_filter.py misc/mypy_ignore.txt

This will output all warning messages not found in mypy_ignore.txt. It will also group them
so that you don't have to read the same message twice. Inspect the output.
If it contains any legitimate errors, or messages that are generic enough to apply to other
situations, fix the code to remove them. Once the output looks safe, run the command again
with 'ok' at the end, i.e:

python3 -m mypy -p birdseye --ignore-missing-imports | misc/mypy_filter.py misc/mypy_ignore.txt ok

This will add any remaining warnings to mypy_ignore.txt so that they are ignored in the future.
"""

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
