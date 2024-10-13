import os
from cheap_repr import repr_str, cheap_repr
from birdseye import eye

path = os.path.join(os.path.expanduser('~'), '.birdseye_test.db')
os.environ.setdefault('BIRDSEYE_DB', 'sqlite:///' + path)

repr_str.maxparts = 30
cheap_repr.raise_exceptions = True

eye.num_samples['big']['list'] = 10
