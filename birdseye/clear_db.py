from birdseye.db import Database

Database(_skip_version_check=True).clear()

print('Database cleared!')
