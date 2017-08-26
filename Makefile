# === makefile ------------------------------------------------------------===

ROOT=$(shell pwd)
CACHE=${ROOT}/.cache
PYENV=${ROOT}/.pyenv
CONF=${ROOT}/conf
APP_NAME=p2pool

-include Makefile.local

.PHONY: all
all: python-env

.PHONY: check
check: all
	"${PYENV}"/bin/coverage run "${PYENV}"/bin/trial p2pool
	"${PYENV}"/bin/coverage xml -o build/report/coverage.xml

.PHONY: run
run: all
	"${PYENV}"/bin/python run_p2pool.py

.PHONY: shell
shell: all
	"${PYENV}"/bin/ipython

.PHONY: mostlyclean
mostlyclean:
	-rm -rf build
	-rm -rf .coverage

.PHONY: clean
clean: mostlyclean
	-rm -rf "${PYENV}"

.PHONY: distclean
distclean: clean
	-rm -rf "${CACHE}"

.PHONY: maintainer-clean
maintainer-clean: distclean
	@echo 'This command is intended for maintainers to use; it'
	@echo 'deletes files that may need special tools to rebuild.'

.PHONY: dist
dist:

# ===--------------------------------------------------------------------===

${CACHE}/pyenv/virtualenv-1.11.6.tar.gz:
	mkdir -p "${CACHE}"/pyenv
	curl -L 'https://pypi.python.org/packages/source/v/virtualenv/virtualenv-1.11.6.tar.gz' >'$@' || { rm -f '$@'; exit 1; }

${CACHE}/pyenv/pyenv-1.11.6-base.tar.gz: ${CACHE}/pyenv/virtualenv-1.11.6.tar.gz
	-rm -rf "${PYENV}"
	mkdir -p "${PYENV}"
	
	# virtualenv is used to create a separate Python installation
	# for this project in ${PYENV}.
	tar \
	    -C "${CACHE}"/pyenv --gzip \
	    -xf "${CACHE}"/pyenv/virtualenv-1.11.6.tar.gz
	python "${CACHE}"/pyenv/virtualenv-1.11.6/virtualenv.py \
	    --clear \
	    --distribute \
	    --never-download \
	    --prompt="(${APP_NAME}) " \
	    "${PYENV}"
	-rm -rf "${CACHE}"/pyenv/virtualenv-1.11.6
	
	# Snapshot the Python environment
	tar -C "${PYENV}" --gzip -cf "$@" .
	rm -rf "${PYENV}"

${CACHE}/pyenv/pyenv-1.11.6-extras.tar.gz: ${CACHE}/pyenv/pyenv-1.11.6-base.tar.gz ${ROOT}/requirements.txt ${CONF}/requirements*.txt
	-rm -rf "${PYENV}"
	mkdir -p "${PYENV}"
	mkdir -p "${CACHE}"/pypi
	
	# Uncompress saved Python environment
	tar -C "${PYENV}" --gzip -xf "${CACHE}"/pyenv/pyenv-1.11.6-base.tar.gz
	find "${PYENV}" -not -type d -print0 >"${ROOT}"/.pkglist
	
	# readline is installed here to get around a bug on Mac OS X
	# which is causing readline to not build properly if installed
	# from pip, and the fact that a different package must be used
	# to support it on Windows/Cygwin.
	if [ "x`uname -s`" = "xCygwin" ]; then \
	    "${PYENV}"/bin/pip install pyreadline; \
	else \
	    "${PYENV}"/bin/easy_install readline; \
	fi
	
	# pip is used to install Python dependencies for this project.
	for reqfile in "${ROOT}"/requirements.txt \
	               "${CONF}"/requirements*.txt; do \
	    "${PYENV}"/bin/python "${PYENV}"/bin/pip install \
	        --download-cache="${CACHE}"/pypi \
	        -r "$$reqfile" || exit 1; \
	done
	
	# Snapshot the Python environment
	cat "${ROOT}"/.pkglist | xargs -0 rm -rf
	tar -C "${PYENV}" --gzip -cf "$@" .
	rm -rf "${PYENV}" "${ROOT}"/.pkglist

.PHONY:
python-env: ${PYENV}/.stamp-h

${PYENV}/.stamp-h: ${CACHE}/pyenv/pyenv-1.11.6-base.tar.gz ${CACHE}/pyenv/pyenv-1.11.6-extras.tar.gz
	-rm -rf "${PYENV}"
	mkdir -p "${PYENV}"
	
	# Uncompress saved Python environment
	tar -C "${PYENV}" --gzip -xf "${CACHE}"/pyenv/pyenv-1.11.6-base.tar.gz
	tar -C "${PYENV}" --gzip -xf "${CACHE}"/pyenv/pyenv-1.11.6-extras.tar.gz
	
	# All done!
	touch "$@"
