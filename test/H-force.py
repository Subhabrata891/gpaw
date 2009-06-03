from ase import *
from ase.calculators import numeric_force
from gpaw.utilities import equal
from gpaw import GPAW

a = 4.0
n = 16
atoms = Atoms([Atom('H', [1.234, 2.345, 3.456])],
                    cell=(a, a, a), pbc=True)
calc = GPAW(nbands=1, gpts=(n, n, n), txt=None,
                  convergence={'eigenstates': 1e-13})
atoms.set_calculator(calc)
f1 = atoms.get_forces()[0]
for i in range(3):
    f2i = numeric_force(atoms, 0, i)
    print f1[i]-f2i
    equal(f1[i], f2i, 0.00022)

