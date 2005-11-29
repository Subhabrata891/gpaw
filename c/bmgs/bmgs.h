#ifndef DOUBLECOMPLEXDEFINED
#  define DOUBLECOMPLEXDEFINED 1
#  ifdef NO_C99_COMPLEX
//   Stupid compiler does not have a "double complex"
     typedef struct { double r, i; } double_complex;
#  else
#    include <complex.h>
     typedef double complex double_complex;
#  endif
#endif

#undef T
#undef Z
#ifndef BMGSCOMPLEX
#  define T double
#  define Z(f) f
#else
#  define T double_complex
#  define Z(f) f ## z
#endif

#ifndef BMGS_H
#define BMGS_H

typedef int bool;

typedef struct
{
  int ncoefs;
  double* coefs;
  long* offsets;
  long n[3];
  long j[3];
} bmgsstencil;

typedef struct
{
  int l;
  double dr;
  int nbins;
  double* data;
} bmgsspline;

bmgsstencil bmgs_stencil(int ncoefs, const double* coefs, const long* offsets, 
			 int range, const long size[3]);
bmgsstencil bmgs_laplace(int k, double scale, const double h[3], const long n[3]);
bmgsstencil bmgs_mslaplaceA(double scale, 
				   const double h[3],
				   const long n[3]);
bmgsstencil bmgs_mslaplaceB(const long n[3]);
bmgsstencil bmgs_gradient(int k, int i, double h, 
			  const long n[3]);
void bmgs_deletestencil(bmgsstencil* spline);
bmgsspline bmgs_spline(int l, double dr, int nbins, double* f);
double bmgs_splinevalue(const bmgsspline* spline, double r);
void bmgs_deletespline(bmgsspline* spline);
void bmgs_radial1(const bmgsspline* spline, 
		  const int n[3], const double C[3],
		  const double h[3],
		  int* b, double* d);
void bmgs_radial2(const bmgsspline* spline, const int n[3],
		  const int* b, const double* d, 
		  double* f, double* g);
void bmgs_radial3(const bmgsspline* spline, int m, 
		  const int n[3], 
		  const double C[3],
		  const double h[3],
		  const double* f, double* a);
void bmgs_radiald3(const bmgsspline* spline, int m, 
		  const int n[3], 
		  const double C[3],
		  const double h[3],
		  const double* f, const double* g, double* a);
void bmgs_fd(const bmgsstencil* s, const double* a, double* b);
void bmgs_cut(const double* a, const int n[3], const int c[3],
	      double* b, const int m[3]);
void bmgs_zero(double* a, const int n[3], const int c[3],
	       const int s[3]);
void bmgs_paste(const double* a, const int n[3],
		double* b, const int m[3], const int c[3]);
void bmgs_pastep(const double* a, const int n[3],
		double* b, const int m[3], const int c[3]);
void bmgs_rotate(const double* a, const int size[3], double* b, double angle,
		 double*, int*, int exact);
void bmgs_translate(double* a, const int sizea[3], const int size[3],
		    const int start1[3], const int start2[3]);
void bmgs_restrict(int k, int p, 
		   double* a, const int n[3], double* b, double* w);
void bmgs_interpolate(int k, int p, 
		      const double* a, const int n[3],
		      double* b, double* w);
// complex routines:
void bmgs_fdz(const bmgsstencil* s, const double_complex* a,
	      double_complex* b);
void bmgs_cutz(const double_complex* a, const int n[3],
	       const int c[3],
	       double_complex* b, const int m[3]);
void bmgs_cutmz(const double_complex* a, const int n[3],
	       const int c[3],
	       double_complex* b, const int m[3], double_complex phase);
void bmgs_zeroz(double_complex* a, const int n[3],
		const int c[3],
		const int s[3]);
void bmgs_pastez(const double_complex* a, const int n[3],
		 double_complex* b, const int m[3],
		 const int c[3]);
void bmgs_pastepz(const double_complex* a, const int n[3],
		  double_complex* b, const int m[3],
		  const int c[3]);
void bmgs_rotatez(const double_complex* a, const int size[3],
		  double_complex* b, double angle,
		  double*, int*, int exact);
void bmgs_translatemz(double_complex* a, const int sizea[3], const int size[3],
		      const int start1[3], const int start2[3],
		      double_complex phase);
void bmgs_restrictz(int k, int p,
		    double_complex* a, 
		    const int n[3], double_complex* b, double_complex* w);
void bmgs_interpolatez(int k, int p,
		       const double_complex* a, const int n[3],
		       double_complex* b, double_complex* w);

#endif
