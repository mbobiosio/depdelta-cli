.PHONY: check format test image

check:
	uv run ruff check . --fix
	uv run pyright

format:
	uv run ruff format .

test:
	uv run pytest

image:
	docker build -t depdelta-cli .
