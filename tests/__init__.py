import os

path = os.path.join(os.path.expanduser('~'), '.birdseye_test.db')

if not os.environ.get('BIRDSEYE_SERVER_RUNNING'):
    # Remove the database to start from scratch
    if os.path.exists(path):
        os.remove(path)

os.environ.setdefault('BIRDSEYE_DB', 'sqlite:///' + path)
