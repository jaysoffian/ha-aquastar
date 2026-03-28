# Development

## Setup

1. [Install `uv`](https://docs.astral.sh/uv/#installation)
2. [Install `prek`](https://github.com/j178/prek?tab=readme-ov-file#installation)
3. Clone this repo
4. Prepare the cloned repo for development: `uv sync && prek install`

## Commits

Run `prek run --all-files` before committing changes. (The `prek install` step you did during setup should ensure this in any case.)

## Testing the client

```bash
export SECTOKEN=your_sectoken_here
uv run python custom_components/toc_aquastar/client.py --help
uv run python custom_components/toc_aquastar/client.py
```
