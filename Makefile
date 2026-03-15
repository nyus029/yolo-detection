PYTHON ?= python3
VENV ?= .venv
UVICORN ?= $(VENV)/bin/uvicorn
PIP ?= $(VENV)/bin/pip
NPM ?= npm
FRONTEND_DIR ?= frontend

.PHONY: setup run dev clean frontend-build frontend-dev dev-all

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt
	cd $(FRONTEND_DIR) && $(NPM) install

run:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

frontend-build:
	cd $(FRONTEND_DIR) && $(NPM) run build

frontend-dev:
	cd $(FRONTEND_DIR) && $(NPM) run dev -- --host 0.0.0.0

dev: run

# フロントエンドとバックエンドを同時に起動
dev-all:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload & cd $(FRONTEND_DIR) && $(NPM) run dev -- --host 0.0.0.0 & wait

clean:
	rm -rf $(VENV)
