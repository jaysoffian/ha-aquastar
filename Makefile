check:
	pre-commit run --all

hassfest:
	podman run --rm -v "$(PWD)/custom_components:/github/workspace" ghcr.io/home-assistant/hassfest

update:
	pre-commit autoupdate
	uv sync --upgrade
