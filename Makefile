.PHONY: run test preflight

run:
	python app.py

test:
	pytest -q

preflight:
	python scripts/ops_preflight.py
