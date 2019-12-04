.PHONY: docs
docs: docs/build

docs/build: docs/source
	sphinx-autobuild -b html --watch ./chi $(ALLSPHINXOPTS) \
		"$<" $@/html

.PHONY: publish
publish:
	rm -rf dist
	python setup.py sdist
	twine upload dist/*.tar.gz
