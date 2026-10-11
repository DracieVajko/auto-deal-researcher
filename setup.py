from setuptools import setup, find_packages

setup(
    name="auto-deal-searcher",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "typer>=0.9.0",
        "playwright>=1.30.0",
        "pydantic>=2.0.0",
        "requests>=2.28.0",
        "markdown>=3.4.0"
    ],
    entry_points={
        "console_scripts": [
            "dealsearcher=src.cli:app",
        ],
    },
    python_requires=">=3.9",
)