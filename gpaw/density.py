# -*- coding: utf-8 -*-
# Copyright (C) 2003  CAMP
# Please see the accompanying LICENSE file for further information.

"""This module defines a density class."""

import sys
from math import pi, sqrt, log
import time

from Numeric import array, Float, dot, NewAxis, zeros, transpose
from LinearAlgebra import solve_linear_equations as solve

from gpaw.density_mixer import Mixer, MixerSum
from gpaw.transformers import Transformer
from gpaw.utilities import pack, unpack2
from gpaw.utilities.complex import cc, real


class Density:
    """Density object.
    
    Attributes:
     =============== =====================================================
     ``nuclei``      List of ``Nucleus`` objects.
     ``gd``          Grid descriptor for coarse grids.
     ``finegd``      Grid descriptor for fine grids.
     ``interpolate`` Function for interpolating the electron density.
     ``mixer``       ``DensityMixer`` object.
     =============== =====================================================

    Soft and smooth pseudo functions on uniform 3D grids:
     ========== =========================================
     ``nt_sG``  Electron density on the coarse grid.
     ``nt_sg``  Electron density on the fine grid.
     ``nt_g``   Electron density on the fine grid.
     ``rhot_g`` Charge density on the fine grid.
     ``nct_G``  Core electron-density on the coarse grid.
     ========== =========================================
    """
    
    def __init__(self, gd, finegd, hund, fixmom, magmom_a, charge, nspins,
                 stencils, mix, timer, fixdensity, kpt_comm, kT,
                 my_nuclei, ghat_nuclei, nuclei, nvalence):
        """Create the Density object."""

        self.hund = hund
        self.magmom_a = magmom_a
        self.nspins = nspins
        self.gd = gd
        self.finegd = finegd
        self.my_nuclei = my_nuclei
        self.ghat_nuclei = ghat_nuclei
        self.nuclei = nuclei
        self.timer = timer
        self.fixdensity = fixdensity
        self.kpt_comm = kpt_comm

        self.comm = gd.comm

        self.nvalence = nvalence
        self.nvalence0 = nvalence + charge

        for nucleus in nuclei:
            charge += (nucleus.setup.Z - nucleus.setup.Nv - nucleus.setup.Nc)
        self.charge = charge
        
        # Allocate arrays for potentials and densities on coarse and
        # fine grids:
        self.nct_G = self.gd.empty()
        self.nt_sG = self.gd.empty(nspins)
        self.rhot_g = self.finegd.empty()
        self.nt_sg = self.finegd.empty(nspins)

        if nspins == 1:
            self.nt_g = self.nt_sg[0]
        else:
            self.nt_g = self.finegd.empty()

        # Number of neighbor grid points used for interpolation (1, 2, or 3):
        nn = stencils[2]

        # Interpolation function for the density:
        self.interpolate = Transformer(self.gd, self.finegd, nn).apply
        
        # Density mixer:
        if nspins == 2 and (not fixmom or kT != 0):
            self.mixer = MixerSum(mix)
        else:
            self.mixer = Mixer(mix, self.gd, nspins)

    def initialize(self):
        """Initialize density.

        The density is initialized from atomic orbitals, and will
        be constructed with the specified magnetic moments and
        obeying Hund's rules if ``hund`` is true."""

        self.timer.start('Init dens.')

        self.nt_sG[:] = self.nct_G
        for magmom, nucleus in zip(self.magmom_a, self.nuclei):
            nucleus.add_atomic_density(self.nt_sG, magmom, self.hund)

        # The nucleus.add_atomic_density() method should be improved
        # so that we don't have to do this scaling: XXX
        if self.nvalence != self.nvalence0:
            x = float(self.nvalence) / self.nvalence0
            for nucleus in self.my_nuclei:
                nucleus.D_sp *= x
            self.nt_sG *= x
                
        # We don't have any occupation numbers.  The initial
        # electron density comes from overlapping atomic densities
        # or from a restart file.  We scale the density to match
        # the compensation charges:

        for nucleus in self.nuclei:
            nucleus.calculate_multipole_moments()
            
        if self.nspins == 1:
            Q = 0.0
            Q0 = 0.0
            for nucleus in self.my_nuclei:
                Q += nucleus.Q_L[0]
                Q0 += nucleus.setup.Delta0
            Q = sqrt(4 * pi) * self.comm.sum(Q)
            Q0 = sqrt(4 * pi) * self.comm.sum(Q0)
            Nt = self.gd.integrate(self.nt_sG)
            # Nt + Q must be equal to minus the total charge:
            if Q0 - Q != 0:
                x = (Nt + Q0 + self.charge) / (Q0 - Q)
                for nucleus in self.my_nuclei:
                    nucleus.D_sp *= x

                for nucleus in self.nuclei:
                    nucleus.calculate_multipole_moments()
            else:
                x = -(self.charge + Q) / Nt
                self.nt_sG *= x

        else:
            Q_s = array([0.0, 0.0])
            for nucleus in self.my_nuclei:
                s = nucleus.setup
                Q_s += 0.5 * s.Delta0 + dot(nucleus.D_sp, s.Delta_pL[:, 0])
            Q_s *= sqrt(4 * pi)
            self.comm.sum(Q_s)
            Nt_s = [self.gd.integrate(nt_G) for nt_G in self.nt_sG]

            M = sum(self.magmom_a)
            x = 1.0
            y = 1.0
            if Nt_s[0] == 0:
                if Nt_s[1] != 0:
                    y = -(self.charge + Q_s[0] + Q_s[1]) / Nt_s[1]
            else:
                if Nt_s[1] == 0:
                    x = -(self.charge + Q_s[0] + Q_s[1]) / Nt_s[0]
                else:
                    x, y = solve(array([[Nt_s[0],  Nt_s[1]],
                                        [Nt_s[0], -Nt_s[1]]]),
                                 array([-Q_s[0] - Q_s[1] - self.charge,
                                        -Q_s[0] + Q_s[1] + M]))

            if self.charge == 0:
                assert 0.83 < x < 1.17, 'x=%f' % x
                assert 0.83 < y < 1.17, 'x=%f' % y

            self.nt_sG[0] *= x
            self.nt_sG[1] *= y

        self.mixer.mix(self.nt_sG, self.comm)

        self.interpolate_pseudo_density()

        self.timer.stop()

    def initialize2(self):
        """Initialize density.

        The density is initialized from atomic orbitals, and will
        be constructed with the specified magnetic moments and
        obeying Hund's rules if ``hund`` is true."""
        
                
        # We don't have any occupation numbers.  The initial
        # electron density comes from overlapping atomic densities
        # or from a restart file.  We scale the density to match
        # the compensation charges:

        for nucleus in self.nuclei:
            nucleus.calculate_multipole_moments()
            
        if self.nspins == 1:

            Q = 0.0
            Q0 = 0.0
            for nucleus in self.my_nuclei:
                Q += nucleus.Q_L[0]
                Q0 += nucleus.setup.Delta0
            Q = sqrt(4 * pi) * self.comm.sum(Q)
            Q0 = sqrt(4 * pi) * self.comm.sum(Q0)
            Nt = self.gd.integrate(self.nt_sG)

            # Nt + Q must be equal to minus the total charge:
            if Q0 - Q != 0:
                x = (Nt + Q0 + self.charge) / (Q0 - Q)
                for nucleus in self.my_nuclei:
                    nucleus.D_sp *= x

                for nucleus in self.nuclei:
                    nucleus.calculate_multipole_moments()
            else:
                x = -(self.charge + Q) / Nt
                self.nt_sG *= x
        else:
            Q_s = array([0.0, 0.0])
            for nucleus in self.my_nuclei:
                s = nucleus.setup
                Q_s += 0.5 * s.Delta0 + dot(nucleus.D_sp, s.Delta_pL[:, 0])
            Q_s *= sqrt(4 * pi)
            self.comm.sum(Q_s)
            Nt_s = [self.gd.integrate(nt_G) for nt_G in self.nt_sG]

            M = sum(self.magmom_a)
            x = 1.0
            y = 1.0
            print Nt_s
            if abs(Nt_s[0]) < 1e-9:
                if abs(Nt_s[1]) > 1e-9:
                    y = -(self.charge + Q_s[0] + Q_s[1]) / Nt_s[1]
            else:
                if abs(Nt_s[1]) < 1e-9:
                    x = -(self.charge + Q_s[0] + Q_s[1]) / Nt_s[0]
                else:
                    x, y = solve(array([[Nt_s[0],  Nt_s[1]],
                                        [Nt_s[0], -Nt_s[1]]]),
                                 array([-Q_s[0] - Q_s[1] - self.charge,
                                        -Q_s[0] + Q_s[1] + M]))

            print x,y
            if self.charge == 0:
                assert 0.83 < x < 1.17, 'x=%f' % x
                #assert 0.83 < y < 1.17, 'x=%f' % y

            self.nt_sG[0] *= x
            self.nt_sG[1] *= y

        self.mixer.mix(self.nt_sG, self.comm)

        self.interpolate_pseudo_density()

    def interpolate_pseudo_density(self):
        """Transfer the density from the coarse to the fine grid."""
        for s in range(self.nspins):
            self.interpolate(self.nt_sG[s], self.nt_sg[s])

        # With periodic boundary conditions, the interpolation will
        # conserve the number of electron.
        if False in self.gd.domain.periodic_c:
            # With zero-boundary conditions in one or more directions,
            # this is not the case.
            for s in range(self.nspins):
                Nt0 = self.gd.integrate(self.nt_sG[s])
                Nt = self.finegd.integrate(self.nt_sg[s])
                if Nt != 0.0:
                    self.nt_sg[s] *= Nt0 / Nt

    def update_pseudo_charge(self):
        if self.nspins == 2:
            self.nt_g[:] = self.nt_sg[0]
            self.nt_g += self.nt_sg[1]

        self.rhot_g[:] = self.nt_g
        
        for nucleus in self.nuclei:
            nucleus.calculate_multipole_moments()

        for nucleus in self.ghat_nuclei:
            nucleus.add_compensation_charge(self.rhot_g)
            
        charge = self.finegd.integrate(self.rhot_g) + self.charge
        if abs(charge) > 1e-7:
            raise RuntimeError('Charge not conserved: excess=%.7f' % charge ) 

    def update(self, kpt_u, symmetry):
        """Calculate pseudo electron-density.

        The pseudo electron-density ``nt_sG`` is calculated from the
        wave functions, the occupation numbers, and the smooth core
        density ``nct_G``, and finally symmetrized and mixed."""

        if self.fixdensity:
            return
        
        self.nt_sG[:] = 0.0

        # Add contribution from all k-points:
        for kpt in kpt_u:
            kpt.add_to_density(self.nt_sG[kpt.s])

        self.kpt_comm.sum(self.nt_sG)

        # add the smooth core density:
        self.nt_sG += self.nct_G

        # Compute atomic density matrices:
        for nucleus in self.my_nuclei:
            ni = nucleus.get_number_of_partial_waves()
            D_sii = zeros((self.nspins, ni, ni), Float)
            for kpt in kpt_u:
                P_ni = nucleus.P_uni[kpt.u]
                D_sii[kpt.s] += real(dot(cc(transpose(P_ni)),
                                             P_ni * kpt.f_n[:, NewAxis]))
            nucleus.D_sp[:] = [pack(D_ii) for D_ii in D_sii]
            self.kpt_comm.sum(nucleus.D_sp)

        comm = self.comm
        
        if symmetry is not None:
            for nt_G in self.nt_sG:
                symmetry.symmetrize(nt_G, self.gd)

            D_asp = []
            for nucleus in self.nuclei:
                if comm.rank == nucleus.rank:
                    D_sp = nucleus.D_sp
                    comm.broadcast(D_sp, nucleus.rank)
                else:
                    ni = nucleus.get_number_of_partial_waves()
                    np = ni * (ni + 1) / 2
                    D_sp = zeros((self.nspins, np), Float)
                    comm.broadcast(D_sp, nucleus.rank)
                D_asp.append(D_sp)

            for s in range(self.nspins):
                D_aii = [unpack2(D_sp[s]) for D_sp in D_asp]
                for nucleus in self.my_nuclei:
                    nucleus.symmetrize(D_aii, symmetry.maps, s)

        self.mixer.mix(self.nt_sG, comm)

        self.interpolate_pseudo_density()

    def move(self):
        self.mixer.reset(self.my_nuclei)
            
        # Set up smooth core density:
        self.nct_G[:] = 0.0
        for nucleus in self.nuclei:
            nucleus.add_smooth_core_density(self.nct_G, self.nspins)

    def calculate_local_magnetic_moments(self):
        spindensity = self.nt_sg[0] - self.nt_sg[1]

        for nucleus in self.nuclei:
            nucleus.calculate_magnetic_moments()
            
        locmom = 0.0
        for nucleus in self.nuclei:
            locmom += nucleus.mom[0]
            mom = array([0.0])
            if nucleus.stepf is not None:
                nucleus.stepf.integrate(spindensity, mom)
                nucleus.mom = array(nucleus.mom + mom[0])
            nucleus.comm.broadcast(nucleus.mom, nucleus.rank)

    def get_density_array(self):
        """Return pseudo-density array."""
        if self.nspins == 2:
            return self.nt_sG
        else:
            return self.nt_sG[0]
    
    def get_all_electron_density(self, gridrefinement=2):
        """Return real all-electron density array."""

        # Refinement of coarse grid, for representation of the AE-density
        if gridrefinement == 1:
            gd = self.gd
            n_sg = self.nt_sG.copy()
        elif gridrefinement == 2:
            gd = self.finegd
            n_sg = self.nt_sg.copy()
        elif gridrefinement == 4:
            # Interpolation function for the density:
            interpolate = Interpolator(self.finegd, 3, Float).apply

            # Extra fine grid
            gd = self.finegd.refine()
            
            # Transfer the pseudo-density to the fine grid:
            n_sg = gd.empty(self.nspins)
            for s in range(self.nspins):
                interpolate(self.nt_sg[s], n_sg[s])
        else:
            raise NotImplementedError

        # Add corrections to pseudo-density to get the AE-density
        splines = {}
        for nucleus in self.nuclei:
            nucleus.add_density_correction(n_sg, self.nspins, gd, splines)
        
        # Return AE-(spin)-density
        if self.nspins == 2:
            return n_sg
        else:
            return n_sg[0]

