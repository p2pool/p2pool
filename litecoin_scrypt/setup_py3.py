from distutils.core import setup, Extension

ltc_scrypt_module = Extension('ltc_scrypt',
                               sources = ['scryptmodule_py3.c',
                                          'scrypt.c'],
                               include_dirs=['.'])

setup (name = 'ltc_scrypt',
       version = '1.0',
       description = 'Bindings for scrypt proof of work used by Litecoin (Python 3)',
       ext_modules = [ltc_scrypt_module])
