# === makefile ------------------------------------------------------------===

ROOT=$(shell pwd)
CACHE_ROOT=${ROOT}/.cache
PKG_ROOT=${ROOT}/.pkg

-include Makefile.local

.PHONY: all
all: ${PKG_ROOT}/.stamp-h

.PHONY: check
check: all
	"${PKG_ROOT}"/bin/coverage run "${PKG_ROOT}"/bin/trial p2pool
	"${PKG_ROOT}"/bin/coverage xml -o build/report/coverage.xml

.PHONY: run
run: all
	"${PKG_ROOT}"/bin/python run_p2pool.py

.PHONY: shell
shell: all
	"${PKG_ROOT}"/bin/ipython

.PHONY: mostlyclean
mostlyclean:
	-rm -rf build
	-rm -rf .coverage

.PHONY: clean
clean: mostlyclean
	-rm -rf "${PKG_ROOT}"

.PHONY: distclean
distclean: clean
	-rm -rf "${CACHE_ROOT}"

.PHONY: maintainer-clean
maintainer-clean: distclean
	@echo 'This command is intended for maintainers to use; it'
	@echo 'deletes files that may need special tools to rebuild.'

.PHONY: dist
dist:

# ===--------------------------------------------------------------------===

${CACHE_ROOT}/virtualenv/virtualenv-1.10.1.tar.gz:
	mkdir -p ${CACHE_ROOT}/virtualenv
	sh -c "cd ${CACHE_ROOT}/virtualenv && curl -O https://pypi.python.org/packages/source/v/virtualenv/virtualenv-1.10.1.tar.gz"

${PKG_ROOT}/.stamp-h: conf/requirements*.pip ${CACHE_ROOT}/virtualenv/virtualenv-1.10.1.tar.gz
	# Because build and run-time dependencies are not thoroughly tracked,
	# it is entirely possible that rebuilding the development environment
	# on top of an existing one could result in a broken build. For the
	# sake of consistency and preventing unnecessary, difficult-to-debug
	# problems, the entire development environment is rebuilt from scratch
	# everytime this make target is selected.
	${MAKE} clean
	
	# The ``${PKG_ROOT}`` directory, if it exists, is removed by the
	# ``clean`` target. The PyPI cache is nonexistant if this is a freshly
	# checked-out repository, or if the ``distclean`` target has been run.
	# This might cause problems with build scripts executed later which
	# assume their existence, so they are created now if they don't
	# already exist.
	mkdir -p "${PKG_ROOT}"
	mkdir -p "${CACHE_ROOT}"/pypi
	
	# ``virtualenv`` is used to create a separate Python installation for
	# this project in ``${PKG_ROOT}``.
	tar \
	  -C "${CACHE_ROOT}"/virtualenv --gzip \
	  -xf "${CACHE_ROOT}"/virtualenv/virtualenv-1.10.1.tar.gz
	python "${CACHE_ROOT}"/virtualenv/virtualenv-1.10.1/virtualenv.py \
	  --clear \
	  --distribute \
	  --never-download \
	  --prompt="(p2pool) " \
	  "${PKG_ROOT}"
	-rm -rf "${CACHE_ROOT}"/virtualenv/virtualenv-1.10.1
	
	# readline is installed here to get around a bug on Mac OS X which is
	# causing readline to not build properly if installed from pip.
	"${PKG_ROOT}"/bin/easy_install readline
	
	# pip is used to install Python dependencies for this project.
	for reqfile in conf/requirements*.pip; do \
	  "${PKG_ROOT}"/bin/python "${PKG_ROOT}"/bin/pip install \
	    --download-cache="${CACHE_ROOT}"/pypi \
	    -r $$reqfile; \
	done
	
	# All done!
	touch "${PKG_ROOT}"/.stamp-h

# ===--------------------------------------------------------------------===
# End of File
# ===--------------------------------------------------------------------===
