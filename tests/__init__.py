import os
from cheap_repr import repr_str, cheap_repr
from birdseye import eye

path = os.path.join(os.path.expanduser('~'), '.birdseye_test.db')

if not os.environ.get('BIRDSEYE_SERVER_RUNNING'):
    # Remove the database to start from scratch
    if os.path.exists(path):
        os.remove(path)

os.environ.setdefault('BIRDSEYE_DB', 'sqlite:///' + path)

repr_str.maxparts = 30
cheap_repr.raise_exceptions = True

eye.num_samples['big']['list'] = 10
