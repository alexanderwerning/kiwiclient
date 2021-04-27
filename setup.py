"""Defines setuptools metadata."""

import setuptools

setuptools.setup(
    name="kiwisdrclient",
    packages=setuptools.find_packages(),
    install_requires=[
        "numpy",
        "soundcard"
    ],
    python_requires=">=3.7",
)

