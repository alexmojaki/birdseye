import os

path = os.path.join(os.path.expanduser('~'), '.birdseye_test.db')

# Remove the database to start from scratch
if os.path.exists(path):
    os.remove(path)

os.environ['BIRDSEYE_DB'] = 'sqlite:///' + path
