# Copyright ClusterHQ Inc.
# See LICENSE file for details.

from setuptools import setup, find_packages
import codecs  # To use a consistent encoding

# Get the long description from the relevant file
with codecs.open('DESCRIPTION.rst', encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='vnx_flocker_driver',
    version='1.0',
    description='EMC VNX Backend Plugin for ClusterHQ/Flocker ',
    long_description=long_description,
    author='Madhuri Yechuri',
    author_email='madhuri.yechuri@clusterhq.com',
    url='https://github.com/ClusterHQ/flocker-vnx-driver',
    license='Apache 2.0',

    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: System Administrators',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries :: Python Modules',

        'License :: OSI Approved :: Apache Software License',

        # Python versions supported
        'Programming Language :: Python :: 2.7',
    ],

    keywords='backend, plugin, flocker, docker, python',
    packages=find_packages(exclude=['test*']),
    install_requires=[''],
    data_files=[('/etc/flocker/', ['example_vnx_agent.yml']),
                ('/etc/flocker/', ['config.yml'])]
)
