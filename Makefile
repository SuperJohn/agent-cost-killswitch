PYTHON ?= python3
export PYTHONPATH := $(CURDIR)

.PHONY: install test run serve record demo

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest -q

run serve:
	$(PYTHON) -m killswitch serve

record demo:
	$(PYTHON) -m killswitch record
