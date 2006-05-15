import Numeric as num
from Numeric import pi
from gridpaw.utilities.complex import real
from FFT import fftnd
from gridpaw.poisson_solver import PoissonSolver
from gridpaw.utilities import DownTheDrain
from gridpaw.utilities.gauss import Gaussian
from gridpaw.utilities.tools import construct_reciprocal

class Coulomb:
    """Class used to evaluate coulomb integrals"""
    def __init__(self, gd):
        """Class should be initialized with a grid_descriptor 'gd' from
           the gridpaw module
        """        
        self.gd = gd

    def load(self, method):
        """Make sure all necessary attributes have been initialized"""
        
        # ensure that requested method is valid
        assert method in ('real', 'recip_gauss', 'recip_ewald'),\
            'Invalid method name, use either real, recip_gauss, or recip_ewald'

        if method.startswith('recip'):
            if self.gd.domain.comm.size > 1:
                raise RuntimeError('Cannot do parallel FFT, ' +\
                                   'use method=\'real\'')
            if not hasattr(self, 'k2'):
                self.k2, self.N3 = construct_reciprocal(self.gd)
                
            if method.endswith('ewald') and not hasattr(self, 'ewald'):
                # cutoff radius
                rc = 0.5 * num.average(self.gd.domain.cell_c)
                # ewald potential: 1 - cos(k rc)
                self.ewald = num.ones(self.gd.N_c) - \
                             num.cos(num.sqrt(self.k2)* rc)
                # lim k ->0 ewald / k2 
                self.ewald[0,0,0] = 0.5 * rc**2

            if method.endswith('gauss') and not hasattr(self, 'ng'):
                gauss = Gaussian(self.gd)
                self.ng = gauss.get_gauss(0) / (2 * num.sqrt(pi))
                self.vg = gauss.get_gauss_pot(0) / (2 * num.sqrt(pi))
        else: # method == 'real'
            if not hasattr(self, 'solve'):
                self.solve = PoissonSolver(self.gd,
                                           out=DownTheDrain(),
                                           load_gauss=True).solve

    def get_single_exchange(self, n, Z=None, method='recip_gauss'):
        """Returns exchange energy of input density 'n' defined as
                                              *
                              /    /      n(r)  n(r')
          -1/2 (n | n) = -1/2 | dr | dr'  ------------
	                      /    /        |r - r'|
	   where n could be complex.
        """
        # determine exchange energy of neutral density using specified method
        return -0.5 * self.coulomb(n1=n, Z1=Z, method=method)

    def coulomb(self, n1, n2=None, Z1=None, Z2=None, method='recip_gauss'):
        """Evaluates the coulomb integral:
                                      *
                      /    /      n1(r)  n2(r')
          (n1 | n2) = | dr | dr'  -------------
	              /    /         |r - r'|
	   where n1 and n2 could be complex.

           real:
           Evaluate directly in real space using gaussians to neutralize
           density n2, such that the potential can be generated by standard
           procedures

           recip_ewald:
           Evaluate by Fourier transform.
           Divergence at division by k^2 is avoided by utilizing the Ewald /
           Tuckermann trick, which formaly requires the densities to be
           localized within half of the unit cell.

           recip_gauss:
           Evaluate by Fourier transform.
           Divergence at division by k^2 is avoided by removing total charge
           of n1 and n2 with gaussian density ng
                                                  *          *    *
           (n1|n2) = (n1 - Z1 ng|n2 - Z2 ng) + (Z2 n1 + Z1 n2 - Z1 Z2 ng | ng)

           The evaluation of the integral (n1 - Z1 ng|n2 - Z2 ng) is done in
           k-space using FFT techniques.
	"""
        self.load(method)
        # determine integrand using specified method
        if method == 'real':
            I = self.gd.new_array()
            if n2 == None: n2 = n1; Z2 = Z1
            self.solve(I, n2, charge=Z2)
            I *= num.conjugate(n1)
        elif method == 'recip_ewald':
            n1k = fftnd(n1)
            if n2 == None: n2k = n1k
            else: n2k = fftnd(n2)
            I = num.conjugate(n1k) * n2k * \
                self.ewald * 4 * pi / (self.k2 * self.N3)
        else: #method == 'recip_gauss':
            # Determine total charges
            if Z1 == None: Z1 = self.gd.integrate(n1)
            if Z2 == None and n2 != None: Z2 = self.gd.integrate(n2)

            # Determine the integrand of the neutral system
            # (n1 - Z1 ng)* int dr'  (n2 - Z2 ng) / |r - r'|
            nk1 = fftnd(n1 - Z1 * self.ng)
            if n2 == None:
                I = num.absolute(nk1)**2 * 4 * pi / (self.k2 * self.N3)
            else:
                nk2 = fftnd(n2 - Z2 * self.ng)
                I = num.conjugate(nk1) * nk2 * 4 * pi / (self.k2 * self.N3)

            # add the corrections to the integrand due to neutralization
            if n2 == None:
                I += (2 * real(num.conjugate(Z1) * n1) - abs(Z1)**2 * self.ng)\
                     * self.vg
            else:
                I += (num.conjugate(Z1) * n2 + Z2 * num.conjugate(n1) -
                      num.conjugate(Z1) * Z2 * self.ng) * self.vg
        if n1.typecode() == num.Float and (n2 == None or
                                           n2.typecode() == num.Float):
            return real(self.gd.integrate(I))
        return self.gd.integrate(I)

def test(N=2**5, a=20):
    from gridpaw.domain import Domain
    from gridpaw.grid_descriptor import GridDescriptor
    from gridpaw.utilities.mpi import world, parallel
    from gridpaw.utilities.gauss import coordinates
    import time

    d  = Domain((a, a, a))    # domain object
    Nc = (N,N,N)              # tuple with number of grid point along each axis
    d.set_decomposition(world, N_c=Nc) # decompose domain on processors
    gd = GridDescriptor(d,Nc) # grid-descriptor object
    xyz, r2 = coordinates(gd) # matrix with the square of the radial coordinate
    r  = num.sqrt(r2)         # matrix with the values of the radial coordinate
    nH = num.exp(-2*r)/pi     # density of the hydrogen atom
    C = Coulomb(gd)           # coulomb calculator
    
    if parallel:
        C.load('real')
        t0 = time.time()
        print 'Processor %s of %s: %s in %s'%(
            d.comm.rank + 1,
            d.comm.size,
            -.5 * C.coulomb(nH, method='real'),
            time.time() - t0)
        return
    else:
        C.load('recip_ewald')
        C.load('recip_gauss')
        C.load('real')
        test = {}
        t0 = time.time()
        test['dual density'] = (-.5 * C.coulomb(nH, nH.copy()),
                                time.time() - t0)
        for method in ('real', 'recip_gauss', 'recip_ewald'):
            t0 = time.time()
            test[method] = (-.5 * C.coulomb(nH, method=method),
                            time.time() - t0)
        return test
