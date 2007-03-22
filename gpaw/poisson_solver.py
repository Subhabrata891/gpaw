# Copyright (C) 2003  CAMP
# Please see the accompanying LICENSE file for further information.

from math import pi
import sys

import Numeric as num

from gpaw.transformers import Transformer
from gpaw.operators import Laplace, LaplaceA, LaplaceB
from gpaw import ConvergenceError


class PoissonSolver:
    def __init__(self, gd, nn, relax='GS', load_gauss=False):
        self.gd = gd
        scale = -0.25 / pi 
        self.dv = gd.dv

        if nn == 'M':
            self.operators = [LaplaceA(gd, -scale)]
            self.B = LaplaceB(gd)
        else:
            self.operators = [Laplace(gd, scale, nn)]
            self.B = None

        # Relaxation method
        if relax == 'GS':
            # Gauss-Seidel
            self.relax_method = 1
        elif relax == 'J':
            # Jacobi
            self.relax_method = 2
        else:
            raise NotImplementedError('Relaxation method %s' % relax)

        self.rhos = [gd.empty()]
        self.phis = [None]
        self.residuals = [gd.empty()]
        self.interpolators = []
        self.restrictors = []

        level = 0
        self.presmooths = [2]
        self.postsmooths = [1]
        
        # Weights for the relaxation,
        # only used if 'J' (Jacobi) is chosen as method
        self.weights = [2.0/3.0]
        
        while level < 4:
            try:
                gd2 = gd.coarsen()
            except ValueError:
                break
            self.operators.append(Laplace(gd2, scale, 1))
            self.phis.append(gd2.empty())
            self.rhos.append(gd2.empty())
            self.residuals.append(gd2.empty())
            self.interpolators.append(Transformer(gd2, gd))
            self.restrictors.append(Transformer(gd, gd2))
            self.presmooths.append(4)
            self.postsmooths.append(4)
            self.weights.append(1.0)
            level += 1
            gd = gd2

        self.levels = level
        self.step = 0.66666666 / self.operators[0].get_diagonal_element()
        self.presmooths[level] = 8
        self.postsmooths[level] = 8

        if load_gauss:
            from gpaw.utilities.gauss import Gaussian
            gauss = Gaussian(self.gd)
            self.rho_gauss = gauss.get_gauss(0)
            self.phi_gauss = gauss.get_gauss_pot(0)
        
    def solve(self, phi, rho, eps=2e-10, charge=0, maxcharge=1e-6):
        self.phis[0] = phi

        # handling of charged densities
        if charge == None:
            charge = self.gd.integrate(rho)
        if abs(charge) > maxcharge:
            # Load necessary attributes
            if not hasattr(self, 'rho_gauss'):
                from gpaw.utilities.gauss import Gaussian
                gauss = Gaussian(self.gd)
                self.rho_gauss = gauss.get_gauss(0)
                self.phi_gauss = gauss.get_gauss_pot(0)
                
            # remove monopole moment
            rho_neutral = rho - self.rho_gauss * charge

            # determine potential from neutralized density
            phi -= self.phi_gauss * charge / (2 * num.sqrt(pi))
            niter = self.solve(phi, rho_neutral, eps=eps, charge=0)

            # correct error introduced by removing monopole
            phi += self.phi_gauss * charge / (2 * num.sqrt(pi))

            return niter

        if self.B is None:
            self.rhos[0][:] = rho
        else:
            self.B.apply(rho, self.rhos[0])
        
        niter = 1
        while self.iterate2(self.step) > eps and niter < 200:
            niter += 1
        if niter == 200:
            charge = num.sum(rho.flat) * self.dv
            print 'CHARGE:', charge
            raise ConvergenceError('Poisson solver did not converge!')

        return niter
        
    def iterate(self, step, level=0):
        residual = self.residuals[level]
        niter = 0
        while True:
            niter += 1
            if level > 0 and niter == 1:
                residual[:] = -self.rhos[level]
            else:
                self.operators[level].apply(self.phis[level], residual)
                residual -= self.rhos[level]
            error = self.gd.comm.sum(num.vdot(residual, residual))
            if niter == 1 and level < self.levels:
                self.restrictors[level].apply(residual, self.rhos[level + 1])
                self.phis[level + 1][:] = 0.0
                self.iterate(4.0 * step, level + 1)
                self.interpolators[level].apply(self.phis[level + 1], residual)
                self.phis[level] -= residual
                continue
            residual *= step
            self.phis[level] -= residual
            if niter == 2:
                break
            
        return error


    def iterate2(self, step, level=0):
        """Smooths the solution in every multigrid level"""

        residual = self.residuals[level]

        if level < self.levels:
            self.operators[level].relax(self.relax_method,
                                        self.phis[level],
                                        self.rhos[level],
                                        self.presmooths[level],
                                        self.weights[level])

            self.operators[level].apply(self.phis[level], residual)
            residual -= self.rhos[level]
            self.restrictors[level].apply(residual,
                                          self.rhos[level + 1])
            self.phis[level + 1][:] = 0.0
            self.iterate2(4.0 * step, level + 1)
            self.interpolators[level].apply(self.phis[level + 1], residual)
            self.phis[level] -= residual

        self.operators[level].relax(self.relax_method,
                                    self.phis[level],
                                    self.rhos[level],
                                    self.postsmooths[level],
                                    self.weights[level])
        if level == 0:
            self.operators[level].apply(self.phis[level], residual)
            residual -= self.rhos[level]
            error = self.gd.domain.comm.sum(num.dot(residual.flat,
                                                    residual.flat)) * self.dv
            return error
