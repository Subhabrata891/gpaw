#ifdef PARALLEL
#include <Python.h>
#define NO_IMPORT_ARRAY
#include <Numeric/arrayobject.h>
#include <mpi.h>
#include "extensions.h"
#include <structmember.h>
#include "mympi.h"

static void mpi_dealloc(MPIObject *obj)
{
  if (obj->comm == MPI_COMM_WORLD)
    MPI_Finalize();
  else
    {
      MPI_Comm_free(&(obj->comm));
      Py_DECREF(obj->parent);
    }
  PyObject_DEL(obj);
}

static PyObject * mpi_receive(MPIObject *self, PyObject *args)
{
  PyArrayObject* a;
  int src;
  int block = 1;
  if (!PyArg_ParseTuple(args, "Oi|i", &a, &src, &block))
    return NULL;
  int n = a->descr->elsize;
  for (int d = 0; d < a->nd; d++)
    n *= a->dimensions[d];
  if (block)
    {
      MPI_Recv(LONGP(a), n, MPI_BYTE, src, 77, self->comm, MPI_STATUS_IGNORE);
      Py_RETURN_NONE;
    }
  else
    {
      MPI_Request req;
      MPI_Irecv(LONGP(a), n, MPI_BYTE, src, 77, self->comm, &req);
      return Py_BuildValue("s#", &req, sizeof(req));
    }
}
 
static PyObject * mpi_send(MPIObject *self, PyObject *args)
{
  PyArrayObject* a;
  int dest;
  int block = 1;
  if (!PyArg_ParseTuple(args, "Oi|i", &a, &dest, &block))
    return NULL;
  int n = a->descr->elsize;
  for (int d = 0; d < a->nd; d++)
    n *= a->dimensions[d];
  if (block)
    {
      MPI_Send(LONGP(a), n, MPI_BYTE, dest, 77, self->comm);
      Py_RETURN_NONE;
    }
  else
    {
      MPI_Request req;
      MPI_Isend(LONGP(a), n, MPI_BYTE, dest, 77, self->comm, &req);
      return Py_BuildValue("s#", &req, sizeof(req));
    }
}
 
static PyObject * mpi_wait(MPIObject *self, PyObject *args)
{
  char* s;
  int n;
  if (!PyArg_ParseTuple(args, "s#", &s, &n))
    return NULL;
  MPI_Wait((MPI_Request*)s, MPI_STATUS_IGNORE);
  Py_RETURN_NONE;
}
 
static PyObject * mpi_sum(MPIObject *self, PyObject *args)
{
  PyObject* obj;
  int root = -1;
  if (!PyArg_ParseTuple(args, "O|i", &obj, &root))
    return NULL;
  if (PyFloat_Check(obj))
    {
      double din = ((PyFloatObject*)obj)->ob_fval;
      double dout;
      if (root == -1)
        MPI_Allreduce(&din, &dout, 1, MPI_DOUBLE, MPI_SUM, self->comm);
      else
        MPI_Reduce(&din, &dout, 1, MPI_DOUBLE, MPI_SUM, root, self->comm);
      return Py_BuildValue("d", dout);
    }
  else
    {
      PyArrayObject* a = (PyArrayObject*)obj;
      int n = 1;
      if (a->descr->type_num == PyArray_CDOUBLE)
        n = 2;
      for (int d = 0; d < a->nd; d++)
        n *= a->dimensions[d];
      if (root == -1)
        {
          double* b = (double*)malloc(n * sizeof(double));
          // XXX Use MPI_IN_PLACE!!
          MPI_Allreduce(LONGP(a), b, n, MPI_DOUBLE, MPI_SUM, self->comm);
          memcpy(LONGP(a), b, n * sizeof(double));
          free(b);
        }
      else
        {
          double* b = 0;
          int rank;
          MPI_Comm_rank(self->comm, &rank);
          if (rank == root)
            b = (double*)malloc(n * sizeof(double));
          // XXX Use MPI_IN_PLACE!!
          MPI_Reduce(LONGP(a), b, n, MPI_DOUBLE, MPI_SUM, root, self->comm);
          if (rank == root)
            {
              memcpy(LONGP(a), b, n * sizeof(double));
              free(b);
            }
        }
      Py_RETURN_NONE;
    }
}
 
static PyObject * mpi_allgather(MPIObject *self, PyObject *args)
{
  PyArrayObject* a;
  PyArrayObject* b;
  if (!PyArg_ParseTuple(args, "OO", &a, &b))
    return NULL;
  int n = a->descr->elsize;
  for (int d = 0; d < a->nd; d++)
    n *= a->dimensions[d];
  // What about endianness????
  MPI_Allgather(LONGP(a), n, MPI_BYTE, LONGP(b), n, MPI_BYTE, self->comm);
  Py_RETURN_NONE;
}
 
static PyObject * mpi_gather(MPIObject *self, PyObject *args)
{
  PyArrayObject* a;
  int root;
  PyArrayObject* b = 0;
  if (!PyArg_ParseTuple(args, "Oi|O", &a, &root, &b))
    return NULL;
  int n = a->descr->elsize;
  for (int d = 0; d < a->nd; d++)
    n *= a->dimensions[d];
  if (b == 0)  // What about endianness????
    MPI_Gather(LONGP(a), n, MPI_BYTE, 0, n, MPI_BYTE, root, self->comm);
  else
    MPI_Gather(LONGP(a), n, MPI_BYTE, LONGP(b), n, MPI_BYTE, root, self->comm);
  Py_RETURN_NONE;
}
 
static PyObject * mpi_broadcast(MPIObject *self, PyObject *args)
{
  PyArrayObject* buf;
  int root;
  if (!PyArg_ParseTuple(args, "Oi", &buf, &root))
    return NULL;
  int n = buf->descr->elsize;
  for (int d = 0; d < buf->nd; d++)
    n *= buf->dimensions[d];
  MPI_Bcast(LONGP(buf), n, MPI_BYTE, root, self->comm);
  Py_RETURN_NONE;
}

// Forward declaration of MPI_Communicator because it needs MPIType
// that needs MPI_getattr that needs MPI_Methods that need
// MPI_Communicator that need ...
static PyObject * MPICommunicator(MPIObject *self, PyObject *args);

static PyMethodDef mpi_methods[] = {
    {"receive",      (PyCFunction)mpi_receive,     METH_VARARGS, 0},
    {"send",         (PyCFunction)mpi_send,        METH_VARARGS, 0},
    {"wait",         (PyCFunction)mpi_wait,        METH_VARARGS, 0},
    {"sum",          (PyCFunction)mpi_sum,         METH_VARARGS, 0},
    {"gather",       (PyCFunction)mpi_gather,      METH_VARARGS, 0},
    {"all_gather",    (PyCFunction)mpi_allgather,   METH_VARARGS, 0},
    {"broadcast",    (PyCFunction)mpi_broadcast,   METH_VARARGS, 0},
    {"new_communicator", (PyCFunction)MPICommunicator, METH_VARARGS, 0},
    {0, 0, 0, 0}
};

static PyMemberDef mpi_members[] = {
  {"size", T_INT, offsetof(MPIObject, size), 0, "Number of processors"},
  {"rank", T_INT, offsetof(MPIObject, rank), 0, "Number of this processor"},
  {0, 0, 0, 0, 0}  /* Sentinel */
};

static int NewMPIObject2(MPIObject* self, PyObject *args, PyObject *kwds)
{
  static char *kwlist[] = {NULL};

  if (! PyArg_ParseTupleAndKeywords(args, kwds, "", kwlist))
    return -1;

  MPI_Init(0, 0);
  MPI_Comm_size(MPI_COMM_WORLD, &(self->size));
  MPI_Comm_rank(MPI_COMM_WORLD, &(self->rank));
  self->comm = MPI_COMM_WORLD;
  return 0;
}


// XXX use PyType_GenericNew !!!!!!!!!
static PyObject *
Noddy_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    MPIObject *self;

    self = (MPIObject *)type->tp_alloc(type, 0);

    return (PyObject *)self;
}

PyTypeObject MPIType = {
  PyObject_HEAD_INIT(&PyType_Type)
  0,                         /*ob_size*/
  "MPI",             /*tp_name*/
  sizeof(MPIObject),             /*tp_basicsize*/
  0,                         /*tp_itemsize*/
  (destructor)mpi_dealloc, /*tp_dealloc*/
  0,                         /*tp_print*/
  //  mpi_get_attr,                         /*tp_getattr*/
  0,                         /*tp_getattr*/
  0,                         /*tp_setattr*/
  0,                         /*tp_compare*/
  0,                         /*tp_repr*/
  0,                         /*tp_as_number*/
  0,                         /*tp_as_sequence*/
  0,                         /*tp_as_mapping*/
  0,                         /*tp_hash */
  0,                         /*tp_call*/
  0,                         /*tp_str*/
  0,                         /*tp_getattro*/
  0,                         /*tp_setattro*/
  0,                         /*tp_as_buffer*/
  Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /*tp_flags*/
  "MPI object",           /* tp_doc */
  0,		               /* tp_traverse */
  0,		               /* tp_clear */
  0,		               /* tp_richcompare */
  0,		               /* tp_weaklistoffset */
  0,		               /* tp_iter */
  0,		               /* tp_iternext */
  mpi_methods,             /* tp_methods */
  mpi_members,
    0,                         /* tp_getset */
    0,                         /* tp_base */
    0,                         /* tp_dict */
    0,                         /* tp_descr_get */
    0,                         /* tp_descr_set */
    0,                         /* tp_dictoffset */
    (initproc)NewMPIObject2,      /* tp_init */
    0,                         /* tp_alloc */
    Noddy_new,                 /* tp_new */ 
};

static PyObject * MPICommunicator(MPIObject *self, PyObject *args)
{
  PyArrayObject* ranks;
  if (!PyArg_ParseTuple(args, "O", &ranks))
    return NULL;
  MPI_Group group;
  MPI_Comm_group(self->comm, &group);
  int n = ranks->dimensions[0];
  MPI_Group newgroup;
  // Stupid hack; MPI_Group_incl wants a int argument;
  // Numeric arrays are long (might be different from ints)
  // More clever ways are welcomed...
  int* ranks_int = (int*) malloc(n*sizeof(int));
  long* ranks_long = LONGP(ranks);
  for (int i=0; i < n ; i++ )
    ranks_int[i]=ranks_long[i];
  MPI_Group_incl(group, n, ranks_int, &newgroup);
  free(ranks_int);
  MPI_Comm comm;
  MPI_Comm_create(self->comm, newgroup, &comm);
  MPI_Group_free(&newgroup);
  MPI_Group_free(&group);
  if (comm == MPI_COMM_NULL) 
    {
      Py_RETURN_NONE;
    }
  else
    {
      MPIObject *obj = PyObject_NEW(MPIObject, &MPIType);
      if (obj == NULL)
        return NULL;
      MPI_Comm_size(comm, &(obj->size));
      MPI_Comm_rank(comm, &(obj->rank));
      obj->comm = comm;
      // Make sure that MPI_COMM_WORLD is kept alive til the end (we
      // don't want MPI_Finalize to be called before MPI_Comm_free):
      Py_INCREF(self);
      obj->parent = (PyObject*)self;
      return (PyObject*)obj;
    }
}

#endif
