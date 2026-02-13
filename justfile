# justfile for jhack project

# Set environment variables
set export := true
PYTHONPATH := "{{invocation_directory()}}:{{invocation_directory()}}/jhack"

# Lock dependencies
lock:
    uv lock -U --no-cache

# Generate requirements.txt
requirements:
    uv pip compile -q --no-cache pyproject.toml -o requirements.txt

# Lint code
lint:
    uv tool run ruff check .
    uv tool run ruff format --check --diff .
    uv run --extra dev pyright

# Format code
fmt:
    uv tool run ruff check --fix-only .
    uv tool run ruff format .

# Run unit tests with coverage
unit:
    uv run --isolated --extra dev coverage run --source=jhack/tests -m pytest --tb native -v -s jhack/tests
    uv run --all-extras coverage report

# Clean build/test artifacts
clean:
    rm -rf .coverage
    rm -rf .pytest_cache
    rm -rf .ruff_cache
    rm -rf .venv
    rm -rf *.charm
    rm -rf *.rock
    rm -rf **/__pycache__
    rm -rf **/*.egg-info
    rm -rf requirements*.txt

