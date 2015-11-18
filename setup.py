# Copyright ClusterHQ Inc.  See LICENSE file for details.

from setuptools import setup, find_packages

with open('DESCRIPTION.rst') as description:
    long_description = description.read()
with open("requirements.txt") as requirements:
    install_requires = requirements.readlines()
with open("dev-requirements.txt") as dev_requirements:
    dev_requires = dev_requirements.readlines()


setup(
    name='flocker_vnx_driver',
    version='0.1',
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
        'Programming Language :: Python :: 2.7',
    ],

    keywords='backend, plugin, flocker, docker, python',
    packages=find_packages(exclude=['test*']),
    install_requires=install_requires,
    extras_require={
        "dev": dev_requires,
    },
)
