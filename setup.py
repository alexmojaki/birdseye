import os
from sys import version_info
import re
import codecs

from setuptools import setup


package = 'birdseye'
dirname = os.path.dirname(__file__)


def file_to_string(*path):
    with codecs.open(os.path.join(dirname, *path), encoding='utf8') as f:
        return f.read()


# __version__ is defined inside the package, but we can't import
# it because it imports dependencies which may not be installed yet,
# so we extract it manually
contents = file_to_string(package, '__init__.py')
__version__ = re.search(r"__version__ = '([.\d]+)'", contents).group(1)


install_requires = ['Flask',
                    'flask-humanize',
                    'sqlalchemy',
                    'asttokens',
                    'littleutils>=0.2',
                    'cheap_repr',
                    'outdated',
                    'cached_property',
                    'future']

if version_info[0] == 2:
    install_requires += ['backports.functools_lru_cache',
                         'typing']

tests_require = [
    'bs4',
    'selenium',
    'requests',
    'pytest',
    'numpy>=1.16.5',
    'pandas',
]

setup(name=package,
      version=__version__,
      description='Graphical Python debugger which lets you easily view '
                  'the values of all evaluated expressions',
      long_description=file_to_string('README.rst'),
      long_description_content_type='test/x-rst',
      classifiers=[
          'License :: OSI Approved :: MIT License',
          'Programming Language :: Python',
          'Programming Language :: Python :: 2',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
          'Programming Language :: Python :: 3.7',
          'Programming Language :: Python :: 3.8',
      ],
      url='http://github.com/alexmojaki/' + package,
      author='Alex Hall',
      author_email='alex.mojaki@gmail.com',
      license='MIT',
      packages=[package],
      install_requires=install_requires,
      tests_require=tests_require,
      extras_require={
          'tests': tests_require,
      },
      test_suite='tests',
      entry_points={
          'console_scripts': ['birdseye=birdseye.server:main'],
      },
      package_data={'': [os.path.join(root, filename)[len('birdseye/'):]
                         for root, dirnames, filenames in os.walk('birdseye')
                         for filename in filenames
                         if not filename.endswith('.pyc')]},
      zip_safe=False)
