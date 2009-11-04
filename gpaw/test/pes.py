from ase import *
from gpaw import *
from gpaw.test import equal
from gpaw.lrtddft import *

from gpaw.pes.dos import DOSPES
from gpaw.pes.tddft import TDDFTPES

txt='/dev/null'
R=0.7 # approx. experimental bond length
a = 3.0
c = 3.0
h = .3
H2 = Atoms([Atom('H', (a / 2, a / 2, (c - R) / 2)),
                Atom('H', (a / 2, a / 2, (c + R) / 2))],
               cell=(a, a, c))

H2_plus = Atoms([Atom('H', (a / 2, a / 2, (c - R) / 2)),
                Atom('H', (a / 2, a / 2, (c + R) / 2))],
               cell=(a, a, c))

xc='LDA'

calc = GPAW(xc=xc, nbands=1, h=h, parsize='domain only',
            spinpol=True, txt=txt)
H2.set_calculator(calc)
e_H2 = H2.get_potential_energy()
niter_H2 = calc.get_number_of_iterations()


calc_plus = GPAW(xc=xc, nbands=2, h=h, parsize='domain only',
                 spinpol=True, txt=txt)
calc_plus.set(charge=+1)
H2_plus.set_calculator(calc_plus)
e_H2_plus = H2_plus.get_potential_energy()
niter_H2_plus = calc.get_number_of_iterations()

lr = LrTDDFT(calc_plus, xc=xc)

pes=DOSPES(calc, calc_plus)
pes.save_folded_pes(filename=txt, folding=None)

pes=TDDFTPES(calc, lr)
pes.save_folded_pes(filename=txt, folding='Gauss')

energy_tolerance = 0.000008
niter_tolerance = 0
equal(e_H2, -3.9459295865, energy_tolerance) # svnversion 5252
equal(niter_H2, 15, niter_tolerance) # svnversion 5252
equal(e_H2_plus, 10.5197088833, energy_tolerance) # svnversion 5252
equal(niter_H2_plus, 15, niter_tolerance) # svnversion 5252
