.PHONY: check test compile

check: compile test

compile:
	python3 -m py_compile src/fpm/*.py

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v
