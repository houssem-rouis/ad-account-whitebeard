PYTHON=./venv/bin/python
APP=app.py

.PHONY: run restart

run:
	$(PYTHON) $(APP)

restart:
	pkill -f "python.*$(APP)" || true
	$(PYTHON) $(APP)
