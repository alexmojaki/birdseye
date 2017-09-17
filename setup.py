from glob import glob

from setuptools import setup

setup(name='birdseye',
      version='0.1.6',
      description='Python debugger using the AST',
      classifiers=[
          'Programming Language :: Python :: 3.5',
      ],
      url='http://github.com/alexmojaki/birdseye',
      author='Alex Hall',
      author_email='alex.mojaki@gmail.com',
      license='MIT',
      packages=['birdseye'],
      install_requires=[
          'flask-humanize',
          'sqlalchemy',
          'asttokens',
          'littleutils',
          'qualname',
      ],
      tests_require=[
          'nose',
          'bs4',
          'numpy',
      ],
      test_suite='nose.collector',
      entry_points={
          'console_scripts': ['birdseye=birdseye.server:main'],
      },
      package_data={'': [x[len('birdseye/'):]
                         for x in glob('birdseye/**/*',
                                       recursive=True)]},
      zip_safe=False)
