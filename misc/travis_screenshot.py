"""
This script lets you view a screenshot of the browser produced by selenium
when a test fails on travis.

To run this script you will first need to:

    pip install pyperclip jsonfinder requests

Open a travis build job with a failed interface test. There should be logs with a big JSON
blob produced by selenium, including an encoding of a screenshot of the browswer when the
error occurred. Copy the URL of the job to your clipboard. Here is an example:

    https://travis-ci.org/alexmojaki/birdseye/jobs/290114752

Then run the script as simply follows:

    python travis_screenshot.py

The script doesn't take arguments, it reads the URL from the clipboard.

The result will be a file such as screen_0.png.

"""

import json
import re
from base64 import b64decode

import pyperclip
import requests
from jsonfinder import jsonfinder

log_url = re.sub(r'.+/(jobs/\d+)', r'https://api.travis-ci.org/\1/log.txt?deansi=true',
                 pyperclip.paste())

text = requests.get(log_url).text

i = 0
for _, _, obj in jsonfinder(text):
    if (isinstance(obj, dict) and
                'selenium' in str(obj) and
                'screen' in obj.get('value', {})):
        obj = obj['value']
        screen = obj.pop('screen')
        message = obj
        try:
            message = message['message']
            message = json.loads(message)
            message = message['errorMessage']
        except (ValueError, KeyError):
            pass
        filename = 'screen_%s.png' % i
        i += 1
        with open(filename, 'wb') as f:
            f.write(b64decode(screen))
            print('Wrote ' + filename)
            print('Message: %s' % message)
