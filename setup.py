from setuptools import setup

setup(name='birdseye',
      version='0.1.1',
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
          'flask_sqlalchemy',
          'asttokens',
          'littleutils',
          'qualname',
      ],
      entry_points={
          'console_scripts': ['birdseye=birdseye.server:main'],
      },
      package_data={'': ['static/**/*', 'templates/*']},
      zip_safe=False)
