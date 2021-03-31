"""Defines setuptools metadata."""

import setuptools

setuptools.setup(
    name="kiwiclient",
    packages=setuptools.find_packages(),
    install_requires=[
        "numpy",
    ],
    python_requires=">=3.7",
)

