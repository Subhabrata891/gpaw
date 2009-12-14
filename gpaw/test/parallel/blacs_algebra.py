"""Test of pblas_pdgemm.  This test requires 4 processors unless other
values of mprocs and nprocs are specified to main().

This is a test of the GPAW interface to the parallel
matrix multiplication routine, pblas_pdgemm.

The test generates random matrices A and B and their product C on master.

Then A and B are distributed, and pblas_dgemm is invoked to get C in
distributed form.  This is then collected to master and compared to
the serially calculated reference.
"""

import sys

import numpy as np

from gpaw.blacs import BlacsGrid, Redistributor, parallelprint
from gpaw.utilities.blas import gemm, gemv, r2k, rk
from gpaw.utilities.blacs import pblas_simple_gemm, pblas_simple_gemv, pblas_simple_r2k, pblas_simple_rk
from gpaw.mpi import world, rank
import _gpaw

tol = 1.0e-13

def main(M=160, N=120, K=140, seed=42, mprocs=2, nprocs=2):
    gen = np.random.RandomState(seed)
    grid = BlacsGrid(world, mprocs, nprocs)

    # Create descriptors for matrices on master:
    globA = grid.new_descriptor(M, K, M, K)
    globB = grid.new_descriptor(K, N, K, N)
    globC = grid.new_descriptor(M, N, M, N)
    globX = grid.new_descriptor(K, 1, K, 1)
    globY = grid.new_descriptor(M, 1, M, 1)
    globD = grid.new_descriptor(M, K, M, K)
    globS = grid.new_descriptor(M, M, M, M)
    globU = grid.new_descriptor(M, M, M, M)

    print globA.asarray()
    # Populate matrices local to master:
    A0 = gen.rand(*globA.shape)
    B0 = gen.rand(*globB.shape)
    D0 = gen.rand(*globD.shape)
    X0 = gen.rand(*globX.shape)

    # Local result matrices
    Y0 = globY.empty()
    C0 = globC.empty()
    S0 = globS.zeros() # zeros needed for rank-updates
    U0 = globU.zeros() # zeros needed for rank-updates

    # Local reference matrix product:
    if rank == 0:
        # C0[:] = np.dot(A0, B0)
        gemm(1.0, B0, A0, 0.0, C0)
        # Y0[:] = np.dot(A0, X0)
        gemv(1.0, A0, X0, 0.0, Y0)
        r2k(1.0, A0, D0, 0.0, S0)
        rk(1.0, A0, 0.0, U0)

    assert globA.check(A0) and globB.check(B0) and globC.check(C0)
    assert globX.check(X0) and globY.check(Y0)
    assert globD.check(D0) and globS.check(S0) and globU.check(U0)

    # Create distributed destriptors with various block sizes:
    distA = grid.new_descriptor(M, K, 2, 2)
    distB = grid.new_descriptor(K, N, 2, 4)
    distC = grid.new_descriptor(M, N, 3, 2)
    distX = grid.new_descriptor(K, 1, 4, 1)
    distY = grid.new_descriptor(M, 1, 3, 1)
    distD = grid.new_descriptor(M, K, 2, 3)
    distS = grid.new_descriptor(M, M, 2, 2)
    distU = grid.new_descriptor(M, M, 2, 2)

    # Distributed matrices:
    A = distA.empty()
    B = distB.empty()
    C = distC.empty()
    X = distX.empty()
    Y = distY.empty()
    D = distD.empty()
    S = distS.zeros() # zeros needed for rank-updates
    U = distU.zeros() # zeros needed for rank-updates

    Redistributor(world, globA, distA).redistribute(A0, A)
    Redistributor(world, globB, distB).redistribute(B0, B)
    Redistributor(world, globX, distX).redistribute(X0, X)
    Redistributor(world, globD, distD).redistribute(D0, D)

    pblas_simple_gemm(distA, distB, distC, A, B, C)
    pblas_simple_gemv(distA, distX, distY, A, X, Y)
    pblas_simple_r2k(distA, distD, distS, A, D, S)
    pblas_simple_rk(distA, distU, A, U)

    # Collect result back on master
    C1 = globC.empty()
    Y1 = globY.empty()
    S1 = globS.zeros() # zeros needed for rank-updates
    U1 = globU.zeros() # zeros needed for rank-updates
    Redistributor(world, distC, globC).redistribute(C, C1)
    Redistributor(world, distY, globY).redistribute(Y, Y1)
    Redistributor(world, distS, globS).redistribute(S, S1)
    Redistributor(world, distU, globU).redistribute(U, U1)

    if rank == 0:
        gemm_err = abs(C1 - C0).max()
        gemv_err = abs(Y1 - Y0).max()
        r2k_err  = abs(S1 - S0).max()
        rk_err   = abs(U1 - U0).max()
        print 'gemm err', gemm_err
        print 'gemv err', gemv_err
        print 'r2k err' , r2k_err
        print 'rk_err'  , rk_err
    else:
        gemm_err = 0.0
        gemv_err = 0.0
        r2k_err  = 0.0
        rk_err   = 0.0

    gemm_err = world.sum(gemm_err) # We don't like exceptions on only one cpu
    gemv_err = world.sum(gemv_err)
    r2k_err  = world.sum(r2k_err)
    rk_err   = world.sum(rk_err)

    assert gemm_err < tol
    assert gemv_err < tol
    assert r2k_err  < tol
    assert rk_err   < tol

if __name__ == '__main__':
    main()
