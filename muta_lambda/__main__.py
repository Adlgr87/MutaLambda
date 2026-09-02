"""Permite ``python -m muta_lambda``. Reenvía a cli/entrypoints.main()."""

from cli.entrypoints import main

if __name__ == "__main__":
    main()
