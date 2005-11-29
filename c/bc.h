#include "bmgs/bmgs.h"
#ifdef PARALLEL
#include <mpi.h>
#else
typedef int* MPI_Request; // !!!!!!!???????????
typedef int* MPI_Comm;
#define MPI_COMM_NULL 0
#define MPI_Comm_rank(comm, rank) *(rank) = 0, 0
#endif


typedef struct
{
  int size1[3];
  int size2[3];
  int sendstart[3][2][3];
  int sendsize[3][2][3];
  int recvstart[3][2][3];
  int recvsize[3][2][3];
  int sendproc[3][2];
  int recvproc[3][2];
  int nsend[3][2];
  int nrecv[3][2];
  int maxsend;
  int maxrecv;
  int padding;
  bool zero[3];
  bool join[3];
  int ndouble;
  double angle;
  double* rotbuf;
  double* rotcoefs;
  int* rotoffsets;
  int exact;
  MPI_Comm comm;
} boundary_conditions;

const static int COPY_DATA = -2;
const static int DO_NOTHING = -3; // ??????????

boundary_conditions* bc_init(const long size1[3], const int padding[2], 
			     const long neighbors[3][2],
			     MPI_Comm comm, bool real, bool cfd);
void bc_unpack1(const boundary_conditions* bc, 
		const double* input, double* output, int i,
		MPI_Request recvreq[2],
		MPI_Request sendreq[2], 
		double* rbuf, double* sbuf,
		const double_complex phases[2]);
void bc_unpack2(const boundary_conditions* bc, 
		double* a2, int i,
		MPI_Request recvreq[2],
		MPI_Request sendreq[2], 
		double* rbuf);
void bc_set_rotation(boundary_conditions* bc,
		     double angle, double* coefs, long* offsets, int exact);
