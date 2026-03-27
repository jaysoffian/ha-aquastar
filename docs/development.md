# Development

## Setup

Requires [uv](https://docs.astral.sh/uv/) and a `pre-commit` wrapper script.

1. [Install `uv`](https://docs.astral.sh/uv/#installation)
2. Create an executable script somewhere in your `PATH` named `pre-commit` with the following contents:

   ```bash
   #!/bin/sh
   exec uvx --isolated --with pre-commit-uv pre-commit "$@"
   ```

3. Clone this repo
4. Set up the dev environment:

   ```bash
   $ uv sync
   $ pre-commit install
   ```

## Commits

Run `pre-commit run --all-files` before committing changes. (The `pre-commit install` step you did during setup should ensure this in any case.)

## Testing the client

```bash
$ export SECTOKEN=your_sectoken_here
$ uv run python -m custom_components.toc_aquastar.client
```

Options:

```bash
$ uv run python -m custom_components.toc_aquastar.client --help
$ uv run python -m custom_components.toc_aquastar.client --days 30
$ uv run python -m custom_components.toc_aquastar.client --start 2025-01-01 --end 2025-01-31
```

## Repo Layout

Run `git ls-files`. Files should be obvious from their names.

You can also use `tree --gitignore` (On macOS, `tree` is available via Homebrew.)

Tip: create a `git tree` alias for yourself:

```bash
git config --global alias.tree '!git ls-files | sed -e "s/[^/]*\//|  /g" -e "s/|  \([^|]\)/|-- \1/"'
```
