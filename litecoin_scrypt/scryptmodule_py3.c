#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "scrypt.h"

static PyObject *scrypt_getpowhash(PyObject *self, PyObject *args)
{
    char *output;
    PyObject *value;
    Py_buffer input;
    
    if (!PyArg_ParseTuple(args, "y*", &input))
        return NULL;
    
    if (input.len != 80) {
        PyBuffer_Release(&input);
        PyErr_SetString(PyExc_ValueError, "Input must be exactly 80 bytes");
        return NULL;
    }
    
    output = PyMem_Malloc(32);
    if (output == NULL) {
        PyBuffer_Release(&input);
        return PyErr_NoMemory();
    }

    scrypt_1024_1_1_256((char *)input.buf, output);
    PyBuffer_Release(&input);
    
    value = Py_BuildValue("y#", output, 32);
    PyMem_Free(output);
    return value;
}

static PyMethodDef ScryptMethods[] = {
    { "getPoWHash", scrypt_getpowhash, METH_VARARGS, "Returns the proof of work hash using scrypt" },
    { NULL, NULL, 0, NULL }
};

static struct PyModuleDef scryptmodule = {
    PyModuleDef_HEAD_INIT,
    "ltc_scrypt",
    "Scrypt proof of work hash for Litecoin",
    -1,
    ScryptMethods
};

PyMODINIT_FUNC PyInit_ltc_scrypt(void) {
    return PyModule_Create(&scryptmodule);
}
