from distutils.core import setup
from distutils.extension import Extension

setup(name="digibyte_subsidys",
    ext_modules=[
        Extension("digibyte_subsidy", ["digibyte_GetBlockBaseValue.cpp"],
        libraries = ["boost_python"])
    ])
