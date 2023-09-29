import setuptools
import sys
import re
import os

if sys.version_info < (3, 9):
    print('dtt requires at least Python 3.9 to run.')
    sys.exit(1)

with open(os.path.join('dtt', '__init__.py'), encoding='utf-8') as f:
    version = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", f.read(), re.M).group(1)

with open('README.md', 'r') as fh:
    long_description = fh.read()

setuptools.setup(
    name='dtt',
    version=version,
    python_requires='>=3.9',
    author='Marshall L Smith Jr',
    author_email='marshallsmithjr@gmail.com',
    description='A ffmpeg workflow manager for transcoding',
    long_description = long_description,
    long_description_content_type = 'text/markdown',
#    extras_require={'with_plexapi': ['plexapi>=3.1.0']},
    url='https://github.com/mlsmithjr/dtt',
    data_files=[('share/doc/dtt', ['README.md', 'Cluster.md', 'config-samples/transcode.yml' ])],
    packages=['dtt'],
    install_requires=['pyyaml >= 5.1', 'rich'],
    entry_points={"console_scripts": ["dtt=dtt.transcode:main"]},
    classifiers=[
      'Programming Language :: Python :: 3',
      'Environment :: Console',
      'Topic :: Multimedia :: Video :: Conversion',
      'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
      'Intended Audience :: End Users/Desktop',
      'Natural Language :: English',
      'Operating System :: POSIX :: Linux',
      'Operating System :: MacOS :: MacOS X',
      'Operating System :: Microsoft :: Windows :: Windows 10',
    ],
    keywords='ffmpeg qsv cuda encode transcode',
)

