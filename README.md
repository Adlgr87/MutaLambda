# MutaLambda

MutaLambda is a Python research project for evolutionary code generation,
multi-island optimization, prompt evolution, sandboxed evaluation, and document
intelligence workflows.

## Project Files

- `muta_lambda.py`: main MutaLambda agent implementation with CLI and integrated tests.
- `mutalambda_v2_patched.py`: patched standalone MutaLambda agent variant.
- `document_intelligence.py`: document parsing and MASSIVE parameter extraction helpers.
- `app.py`: Inferless-style Hugging Face text-generation model wrapper.

## Setup

Use Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

Run the integrated MutaLambda test suite:

```bash
python muta_lambda.py --test
```

Run the patched standalone variant:

```bash
python mutalambda_v2_patched.py --test
```

Run a demo evolution cycle:

```bash
python muta_lambda.py --generations 5 --islands 2
```

`app.py` downloads `tiiuae/falcon-7b-instruct`, uses `trust_remote_code=True`,
and assumes CUDA device `0`. Use it only in an environment prepared for large
Hugging Face model downloads and GPU inference.

`document_intelligence.py` expects an OpenAI-compatible LLM client for semantic
extraction. PDF, spreadsheet, and image support depend on the optional packages
listed in `requirements.txt`.
