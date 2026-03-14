PYTHON ?= python3
VENV ?= .venv
UVICORN ?= $(VENV)/bin/uvicorn
PIP ?= $(VENV)/bin/pip

.PHONY: setup run dev clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt

run:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

dev: run

clean:
	rm -rf $(VENV)
