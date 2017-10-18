import os

os.environ['BIRDSEYE_DB'] = 'sqlite:///' + os.path.join(os.path.expanduser('~'),
                                                        '.birdseye_test.db')
