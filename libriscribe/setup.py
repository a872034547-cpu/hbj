from setuptools import setup, find_packages

setup(
    name="libriscribe",
    version="0.3.0",
    packages=find_packages(where="src", include=[
        "libriscribe",
        "libriscribe.agents",
        "libriscribe.utils",
        "libriscribe.rag",
        "libriscribe.rag.*",
        "libriscribe.memory",
        "libriscribe.memory.*",
        "libriscribe.workflow",
        "libriscribe.workflow.*",
        "libriscribe.export",
        "libriscribe.export.*",
        "libriscribe.web",
        "libriscribe.web.*",
    ]),
    package_dir={"": "src"},
    install_requires=[
        # Existing dependencies
        "typer",
        "openai",
        "python-dotenv",
        "pydantic",
        "pydantic-settings",
        "beautifulsoup4",
        "requests",
        "markdown",
        "fpdf",
        "tenacity",
        # RAG dependencies
        "chromadb>=0.5.0",
        "unstructured[all-docs]>=0.15.0",
        "sentence-transformers>=3.0.0",
        # LangGraph workflow dependencies
        "langgraph>=0.2.0",
        "langchain-core>=0.3.0",
        # Export dependencies
        "python-docx>=1.1.0",
        "pypandoc>=1.14",
        # Web UI dependencies
        "streamlit>=1.38.0",
    ],
    entry_points={
        "console_scripts": [
            "libriscribe=libriscribe.main:app",
            "libriscribe-web=libriscribe.web.app:main",
        ],
    },
)