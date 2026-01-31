#!/bin/bash
# Build script for ltc_scrypt module
# Supports both Python 2 (PyPy) and Python 3

set -e

echo "=== Building ltc_scrypt module ==="
echo ""

# Detect Python versions available
HAS_PYTHON2=0
HAS_PYTHON3=0
HAS_PYPY=0

if command -v python2 &> /dev/null; then
    HAS_PYTHON2=1
    echo "✓ Found Python 2: $(python2 --version 2>&1)"
fi

if command -v pypy &> /dev/null; then
    HAS_PYPY=1
    echo "✓ Found PyPy: $(pypy --version 2>&1 | head -1)"
fi

if command -v python3 &> /dev/null; then
    HAS_PYTHON3=1
    echo "✓ Found Python 3: $(python3 --version)"
fi

echo ""

# Build for Python 2/PyPy
if [ $HAS_PYTHON2 -eq 1 ] || [ $HAS_PYPY -eq 1 ]; then
    echo "Building for Python 2..."
    if [ $HAS_PYPY -eq 1 ]; then
        echo "  Using PyPy (recommended for p2pool)"
        pypy setup.py build
        echo "  Installing for PyPy..."
        pypy setup.py install --user
    elif [ $HAS_PYTHON2 -eq 1 ]; then
        echo "  Using Python 2"
        python2 setup.py build
        echo "  Installing for Python 2..."
        python2 setup.py install --user
    fi
    echo "  ✓ Python 2 build complete"
    echo ""
fi

# Build for Python 3
if [ $HAS_PYTHON3 -eq 1 ]; then
    echo "Building for Python 3..."
    python3 setup_py3.py build
    echo "  Installing for Python 3..."
    python3 setup_py3.py install --user
    echo "  ✓ Python 3 build complete"
    echo ""
fi

# Summary
echo "=== Build Summary ==="
if [ $HAS_PYTHON2 -eq 1 ] || [ $HAS_PYPY -eq 1 ]; then
    echo "✓ Python 2/PyPy module installed"
fi
if [ $HAS_PYTHON3 -eq 1 ]; then
    echo "✓ Python 3 module installed"
fi

if [ $HAS_PYTHON2 -eq 0 ] && [ $HAS_PYPY -eq 0 ] && [ $HAS_PYTHON3 -eq 0 ]; then
    echo "✗ No Python interpreter found!"
    echo "  Please install python2, pypy, or python3"
    exit 1
fi

echo ""
echo "To test the installation, run:"
if [ $HAS_PYPY -eq 1 ]; then
    echo "  pypy test_scrypt.py"
elif [ $HAS_PYTHON2 -eq 1 ]; then
    echo "  python2 test_scrypt.py"
fi
if [ $HAS_PYTHON3 -eq 1 ]; then
    echo "  python3 test_scrypt.py"
fi
