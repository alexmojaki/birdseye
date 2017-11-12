import os
from sys import version_info

from setuptools import setup

install_requires = ['Flask',
                    'flask-humanize',
                    'sqlalchemy',
                    'asttokens',
                    'littleutils',
                    'qualname',
                    'future']

if version_info[0] == 2:
    install_requires += ['backports.functools_lru_cache',
                         'typing']

setup(name='birdseye',
      version='0.1.12',
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
      url='http://github.com/alexmojaki/birdseye',
      author='Alex Hall',
      author_email='alex.mojaki@gmail.com',
      license='MIT',
      packages=['birdseye'],
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
