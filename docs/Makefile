# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SPHINXAPI     = sphinx-apidoc
SPHINXAPISRC  = ../esptest
SPHINXAPIOUT  = api/_generated
SOURCEDIR     = .
BUILDDIR      = _build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help apidoc clean Makefile

# Regenerate the auto API stubs from docstrings.
apidoc:
	@$(SPHINXAPI) --force --separate --module-first -o "$(SPHINXAPIOUT)" "$(SPHINXAPISRC)"

clean:
	@rm -rf "$(BUILDDIR)" "$(SPHINXAPIOUT)"

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile apidoc
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
