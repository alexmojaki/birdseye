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
