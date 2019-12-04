
.PHONY: docs
docs: docs/build

docs/build: docs/source
	sphinx-autobuild -b html --watch ./chi $(ALLSPHINXOPTS) \
		"$<" $@/html
