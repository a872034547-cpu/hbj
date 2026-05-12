---
sidebar_position: 2
---

# Getting Started

This guide will walk you through the installation and setup of LibriScribe.

## Prerequisites

*   **Python 3.7 or later:** Check with `python --version` or `python3 --version`.
*   **pip:** Usually included with Python.
*   **LLM API Key:** Get an API key from one of the following services:

    - **OpenAI:** [Get API Key](https://platform.openai.com/signup/)
    - **Anthropic:** [Get API Key](https://console.anthropic.com/)
    - **DeepSeek:** [Get API Key](https://platform.deepseek.com/)
    - **Google AI Studio (Gemini):** [Get API Key](https://aistudio.google.com/)
    - **Mistral AI:** [Get API Key](https://console.mistral.ai/)



## Installation Steps

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/guerra2fernando/libriscribe.git
    cd libriscribe
    ```

2.  **Install in editable mode:**

    ```bash
    pip install -e .
    ```
    This installs LibriScribe so that changes to the source code are reflected immediately.

3.  **Set up your LLM API Key:**
    *   Create a `.env` file in the *root* directory of the project.
    *   Add your key:

        ```
        OPENAI_API_KEY=your_api_key_here
        GOOGLE_AI_STUDIO_API_KEY=your_api_key_here
        CLAUDE_API_KEY=your_api_key_here
        DEEPSEEK_API_KEY=your_api_key_here
        MISTRAL_API_KEY=your_api_key_here
        ```
        Replace `your_api_key_here` of the LLM that you want to use.  Make sure `.env` is in your `.gitignore`!

## Verifying the Installation

After installation, run:

```bash
libriscribe --help
```