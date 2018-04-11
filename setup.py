import os
from sys import version_info
import re

from setuptools import setup


package = 'birdseye'

# __version__ is defined inside the package, but we can't import
# it because it imports dependencies which may not be installed yet,
# so we extract it manually
init_path = os.path.join(os.path.dirname(__file__),
                         package,
                         '__init__.py')
with open(init_path) as f:
    contents = f.read()
__version__ = re.search(r"__version__ = '([.\d]+)'", contents).group(1)


install_requires = ['Flask',
                    'flask-humanize',
                    'sqlalchemy',
                    'asttokens',
                    'littleutils',
                    'cheap_repr',
                    'outdated',
                    'future']

if version_info[0] == 2:
    install_requires += ['backports.functools_lru_cache',
                         'typing']

setup(name=package,
      version=__version__,
      description='Quick, convenient, expression-centric, graphical Python debugger using the AST',
      classifiers=[
          'License :: OSI Approved :: MIT License',
          'Programming Language :: Python',
          'Programming Language :: Python :: 2',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
      ],
      url='http://github.com/alexmojaki/' + package,
      author='Alex Hall',
      author_email='alex.mojaki@gmail.com',
      license='MIT',
      packages=[package],
      install_requires=install_requires,
      tests_require=[
          'bs4',
          'selenium',
          'requests',
      ],
      test_suite='tests',
      entry_points={
          'console_scripts': ['birdseye=birdseye.server:main'],
      },
      package_data={'': [os.path.join(root, filename)[len('birdseye/'):]
                         for root, dirnames, filenames in os.walk('birdseye')
                         for filename in filenames
                         if not filename.endswith('.pyc')]},
      zip_safe=False)
