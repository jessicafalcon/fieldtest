# `make check` is the gate every commit and PR passes: lint, types, tests, records.
# Every target is read-only on the source tree, so review agents may run it.
.PHONY: check lint typecheck test records security

check: lint typecheck test records

lint:
	uv run --frozen ruff check .
	uv run --frozen ruff format --check .

typecheck:
	uv run --frozen mypy

test:
	uv run --frozen pytest -q

records:
	uv run --frozen python scripts/check_records.py

# Network checks, run by CI's `security` job and before a dependency PR: known
# vulnerabilities in the locked dependencies, and the workflows' static analysis.
security:
	uv export --frozen --all-groups --no-emit-project --format requirements.txt > .venv/requirements-audit.txt
	uvx pip-audit==2.10.1 --strict --disable-pip --require-hashes -r .venv/requirements-audit.txt
	uvx zizmor==1.31.1 --offline .github/workflows
