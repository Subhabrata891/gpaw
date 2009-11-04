import os
from ase import *
from ase.parallel import rank, barrier
from gpaw import GPAW
from gpaw.test import equal, gen
from gpaw.vdw import FFTVDWFunctional

gen('Ar', xcname='revPBE')

energy_tolerance = 0.000002
niter_tolerance = 0

def test():
    vdw = FFTVDWFunctional(verbose=1)
    d = 3.9
    x = d / sqrt(3)
    L = 3.0 + 2 * 4.0
    dimer = Atoms('Ar2', [(0, 0, 0), (x, x, x)], cell=(L, L, L))
    dimer.center()
    calc = GPAW(h=0.2, xc='revPBE')
    dimer.set_calculator(calc)
    e2 = dimer.get_potential_energy()
    niter2 = calc.get_number_of_iterations()
    calc.write('Ar2.gpw')
    e2vdw = calc.get_xc_difference(vdw)
    e2vdwb = GPAW('Ar2.gpw').get_xc_difference(vdw)
    print e2vdw - e2vdw
    assert abs(e2vdw - e2vdw) < 1e-9
    del dimer[1]
    e = dimer.get_potential_energy()
    niter = calc.get_number_of_iterations()
    evdw = calc.get_xc_difference(vdw)

    E = 2 * e - e2
    Evdw = E + 2 * evdw - e2vdw
    print E, Evdw
    assert abs(E - -0.0048) < 1e-4
    assert abs(Evdw - +0.0223) < 1e-4

    print e2, e
    equal(e2, 0.041356501339, energy_tolerance) # svnversion 5252
    equal(niter2, 18, niter_tolerance) # svnversion 5252
    equal(e, 0.0182702058518, energy_tolerance) # svnversion 5252
    equal(niter, 14, niter_tolerance) # svnversion 5252

test()
