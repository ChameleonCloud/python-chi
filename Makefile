.PHONY: docs
docs: docs/build

docs/build: docs/source
	sphinx-autobuild -b html --watch ./chi $(ALLSPHINXOPTS) \
		"$<" $@/html

.PHONY: publish
publish:
	rm -rf build dist
	python setup.py sdist bdist_wheel
	twine upload dist/*.tar.gz
