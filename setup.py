"""Setup per Bug Bounty Scanner."""

from setuptools import setup, find_packages

setup(
    name="bugbounty-scanner",
    version="1.0.0",
    description="Agent automatico per la scansione di vulnerabilita bug bounty",
    author="Raffaele De Vita",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "requests>=2.31.0",
        "urllib3>=2.0.0",
        "beautifulsoup4>=4.12.0",
        "dnspython>=2.4.0",
        "Jinja2>=3.1.0",
    ],
    entry_points={
        "console_scripts": [
            "bbscanner=bugbounty_scanner.cli:main",
        ],
    },
)
