# -*- coding: utf-8 -*-
# Copyright (C) 2003  CAMP
# Please see the accompanying LICENSE file for further information.

if __name__ == '__main__':
    print """\
You are using the wrong setup.py script!  This setup.py defines a
Setup class used to hold the atomic data needed for a specific atom.
For building the GPAW code you must use the setup.py distutils script
at the root of the code tree.  Just do "cd .." and you will be at the
right place."""
    raise SystemExit

import os
import sys
from math import pi, sqrt

import numpy as np
from ase.data import atomic_names, chemical_symbols, atomic_numbers
from ase.units import Bohr, Hartree

from gpaw.setup_data import SetupData
from gpaw.basis_data import Basis
from gpaw.gaunt import gaunt as G_LLL, Y_LLv
from gpaw.spline import Spline
from gpaw.grid_descriptor import RadialGridDescriptor
from gpaw.utilities import unpack, pack, hartree, divrl
from gpaw.rotation import rotation
from gpaw import extra_parameters


def create_setup(symbol, xc, lmax=0,
                 type='paw', basis=None, setupdata=None, world=None):
    if setupdata is None:
        if type == 'hgh' or type == 'hgh.sc':
            lmax = 0
            from gpaw.hgh import HGHSetupData, setups, sc_setups
            if type == 'hgh.sc':
                table = sc_setups
            else:
                table = setups
            parameters = table[symbol]
            setupdata = HGHSetupData(parameters)
        elif type == 'ah':
            from gpaw.ah import AppelbaumHamann
            ah = AppelbaumHamann()
            ah.build(basis)
            return ah
        elif type == 'ghost':
            from gpaw.lcao.bsse import GhostSetupData
            setupdata = GhostSetupData(symbol)
        else:
            setupdata = SetupData(symbol, xc.get_setup_name(),
                                  type, True,
                                  world=world)
    if hasattr(setupdata, 'build'):
        return LeanSetup(setupdata.build(xc, lmax, basis))
    else:
        return setupdata


class BaseSetup:
    """Mixin-class for setups.

    This makes it possible to inherit the most important methods without
    the cumbersome constructor of the ordinary Setup class.

    Maybe this class will be removed in the future, or it could be
    made a proper base class with attributes and so on."""
    
    def print_info(self, text):
        self.data.print_info(text, self)

    def get_basis_description(self):
        return self.basis.get_description()

    def calculate_initial_occupation_numbers(self, magmom, hund, charge,
                                             nspins, f_j=None):
        """If f_j is specified, custom occupation numbers will be used.

        Hund rules disabled if so."""
        
        niao = self.niAO
        f_si = np.zeros((nspins, niao))

        assert (not hund) or f_j is None
        if f_j == None:
            f_j = self.f_j

        # Projector function indices:
        nj = len(self.n_j)

        f_j = np.array(f_j, float)
        if charge >= 0:
            for j in range(nj - 1, -1, -1):
                f = f_j[j]
                c = min(f, charge)
                f_j[j] -= c
                charge -= c
        else:
            for j in range(nj):
                f = f_j[j]
                l = self.l_j[j]
                c = min(2 * (2 * l + 1) - f, -charge)
                f_j[j] += c
                charge += c
        assert charge == 0.0

        i = 0
        j = 0
        for phit in self.phit_j:
            l = phit.get_angular_momentum_number()

            # Skip projector functions not in basis set:
            while j < nj and self.l_j[j] != l:
                j += 1
            if j < nj:
                f = f_j[j]
            else:
                f = 0

            degeneracy = 2 * l + 1

            if hund:
                # Use Hunds rules:
                #assert f == int(f)
                f = int(f)
                f_si[0, i:i + min(f, degeneracy)] = 1.0      # spin up
                f_si[1, i:i + max(f - degeneracy, 0)] = 1.0  # spin down
                if f < degeneracy:
                    magmom -= f
                else:
                    magmom -= 2 * degeneracy - f
            else:
                if nspins == 1:
                    f_si[0, i:i + degeneracy] = 1.0 * f / degeneracy
                else:
                    maxmom = min(f, 2 * degeneracy - f)
                    mag = magmom
                    if abs(mag) > maxmom:
                        mag = cmp(mag, 0) * maxmom
                    f_si[0, i:i + degeneracy] = 0.5 * (f + mag) / degeneracy
                    f_si[1, i:i + degeneracy] = 0.5 * (f - mag) / degeneracy
                    magmom -= mag
                
            i += degeneracy
            j += 1

        #These lines disable the calculation of charged atoms!
        #Therefore I commented them. -Mikael
        #if magmom != 0:
        #    raise RuntimeError('Bad magnetic moment %g for %s atom!'
        # % (magmom, self.self.symbol))
        assert i == niao

        return f_si
    
    def initialize_density_matrix(self, f_si):
        nspins, niao = f_si.shape
        ni = self.ni

        D_sii = np.zeros((nspins, ni, ni))
        D_sp = np.zeros((nspins, ni * (ni + 1) // 2))
        nj = len(self.n_j)
        j = 0
        i = 0
        ib = 0
        for phit in self.phit_j:
            l = phit.get_angular_momentum_number()
            # Skip projector functions not in basis set:
            while j < nj and self.l_j[j] != l:
                i += 2 * self.l_j[j] + 1
                j += 1
            if j == nj:
                break

            for m in range(2 * l + 1):
                D_sii[:, i + m, i + m] = f_si[:, ib + m]
            j += 1
            i += 2 * l + 1
            ib += 2 * l + 1
        for s in range(nspins):
            D_sp[s] = pack(D_sii[s])
        return D_sp

    def symmetrize(self, a, D_aii, map_sa):
        D_ii = np.zeros((self.ni, self.ni))
        for s, R_ii in enumerate(self.R_sii):
            D_ii += np.dot(R_ii, np.dot(D_aii[map_sa[s][a]],
                                        np.transpose(R_ii)))
        return D_ii / len(map_sa)

    def calculate_rotations(self, R_slmm):
        nsym = len(R_slmm)
        self.R_sii = np.zeros((nsym, self.ni, self.ni))
        i1 = 0
        for l in self.l_j:
            i2 = i1 + 2 * l + 1
            for s, R_lmm in enumerate(R_slmm):
                self.R_sii[s, i1:i2, i1:i2] = R_lmm[l]
            i1 = i2

    def get_partial_waves(self):
        """Return spline representation of partial waves and densities."""

        l_j = self.l_j
        nj = len(l_j)
        beta = self.beta

        # cutoffs
        rcut2 = 2 * max(self.rcut_j)
        gcut2 = 1 + int(rcut2 * self.ng / (rcut2 + beta))

        # radial grid
        g = np.arange(self.ng, dtype=float)
        r_g = beta * g / (self.ng - g)

        data = self.data

        # Construct splines:
        nc_g = data.nc_g.copy()
        nct_g = data.nct_g.copy()
        tauc_g = data.tauc_g
        tauct_g = data.tauct_g
        #nc_g[gcut2:] = nct_g[gcut2:] = 0.0
        nc = Spline(0, rcut2, nc_g, r_g, beta, points=1000)
        nct = Spline(0, rcut2, nct_g, r_g, beta, points=1000)
        if tauc_g is None:
            tauc_g = np.zeros(nct_g.shape)
            tauct_g = tauc_g
        tauc = Spline(0, rcut2, tauc_g, r_g, beta, points=1000)
        tauct = Spline(0, rcut2, tauct_g, r_g, beta, points=1000)
        phi_j = []
        phit_j = []
        for j, (phi_g, phit_g) in enumerate(zip(data.phi_jg, data.phit_jg)):
            l = l_j[j]
            phi_g = phi_g.copy()
            phit_g = phit_g.copy()
            phi_g[gcut2:] = phit_g[gcut2:] = 0.0
            phi_j.append(Spline(l, rcut2, phi_g, r_g, beta, points=100))
            phit_j.append(Spline(l, rcut2, phit_g, r_g, beta, points=100))
        return phi_j, phit_j, nc, nct, tauc, tauct

    def set_hubbard_u(self, U, l,scale=1,store=0,LinRes=0):
        """Set Hubbard parameter.
        U in atomic units, l is the orbital to which we whish to
        add a hubbard potential and scale enables or desables the
        scaling of the overlap between the l orbitals, if true we enforce
        <p|p>=1
        Note U is in atomic units
        """
        
        self.HubLinRes=LinRes;
        self.Hubs = scale;
        self.HubStore=store;
        self.HubOcc=[];
        self.HubU = U;
        self.Hubl = l;
        self.Hubi = 0;
        for ll in self.l_j:
            if ll == self.Hubl:
                break
            self.Hubi = self.Hubi + 2 * ll + 1

    def four_phi_integrals(self):
        """Calculate four-phi integral.

        Calculate the integral over the product of four all electron
        functions in the augmentation sphere, i.e.::

          /
          | d vr  ( phi_i1 phi_i2 phi_i3 phi_i4
          /         - phit_i1 phit_i2 phit_i3 phit_i4 ),

        where phi_i1 is an all electron function and phit_i1 is its
        smooth partner.
        """
        if hasattr(self, 'I4_pp'):
            return self.I4_pp

        # radial grid
        ng = self.ng
        g = np.arange(ng, dtype=float)
        r2dr_g = self.beta**3 * g**2 * ng / (ng - g)**4

        phi_jg = self.data.phi_jg
        phit_jg = self.data.phit_jg

        # compute radial parts
        nj = len(self.l_j)
        R_jjjj = np.empty((nj, nj, nj, nj))
        for j1 in range(nj):
            for j2 in range(nj):
                for j3 in range(nj):
                    for j4 in range(nj):
                        R_jjjj[j1, j2, j3, j4] = np.dot(r2dr_g,
                         phi_jg[j1] * phi_jg[j2] * phi_jg[j3] * phi_jg[j4] -
                         phit_jg[j1] * phit_jg[j2] * phit_jg[j3] * phit_jg[j4])

        # prepare for angular parts
        L_i = []
        j_i = []
        for j, l in enumerate(self.l_j):
            for m in range(2 * l + 1):
                L_i.append(l**2 + m)
                j_i.append(j)
        ni = len(L_i)
        # j_i is the list of j values
        # L_i is the list of L (=l**2+m for 0<=m<2*l+1) values
        # https://wiki.fysik.dtu.dk/gpaw/devel/overview.html

        # calculate the integrals
        _np = ni * (ni + 1) // 2 # length for packing
        self.I4_pp = np.empty((_np, _np))
        p1 = 0
        for i1 in range(ni):
            L1 = L_i[i1]
            j1 = j_i[i1]
            for i2 in range(i1, ni):
                L2 = L_i[i2]
                j2 = j_i[i2]
                p2 = 0
                for i3 in range(ni):
                    L3 = L_i[i3]
                    j3 = j_i[i3]
                    for i4 in range(i3, ni):
                        L4 = L_i[i4]
                        j4 = j_i[i4]
                        self.I4_pp[p1, p2] = (np.dot(G_LLL[L1, L2],
                                                     G_LLL[L3, L4]) *
                                              R_jjjj[j1, j2, j3, j4])
                        p2 += 1
                p1 += 1

        # To unpack into I4_iip do:
        # from gpaw.utilities import unpack
        # I4_iip = np.empty((ni, ni, _np)):
        # for p in range(_np):
        #     I4_iip[..., p] = unpack(I4_pp[:, p])

        return self.I4_pp


class LeanSetup(BaseSetup):
    """Setup class with minimal attribute set.

    A setup-like class must define at least the attributes of this
    class in order to function in a calculation."""
    def __init__(self, s):
        """Copies precisely the necessary attributes of the Setup s."""
        # R_sii and HubU can be changed dynamically (which is ugly)
        self.R_sii = None # rotations, initialized when doing sym. reductions
        self.HubU = s.HubU # XXX probably None
        self.lq  = s.lq # Required for LDA+U I think.
        self.type = s.type # required for writing to file
        self.fingerprint = s.fingerprint # also req. for writing
        self.filename = s.filename

        self.symbol = s.symbol
        self.Z = s.Z
        self.Nv = s.Nv
        self.Nc = s.Nc

        self.ni = s.ni
        self.niAO = s.niAO # XXX rename to nao

        self.pt_j = s.pt_j
        self.phit_j = s.phit_j # basis functions

        self.Nct = s.Nct
        self.nct = s.nct

        self.lmax = s.lmax
        self.ghat_l = s.ghat_l
        self.rcgauss = s.rcgauss
        self.vbar = s.vbar

        self.Delta_pL = s.Delta_pL
        self.Delta0 = s.Delta0

        self.E = s.E
        self.Kc = s.Kc
        
        self.M = s.M
        self.M_p = s.M_p
        self.M_pp = s.M_pp
        self.K_p = s.K_p
        self.MB = s.MB
        self.MB_p = s.MB_p

        self.dO_ii = s.dO_ii

        self.xc_correction = s.xc_correction

        # Required to calculate initial occupations
        self.f_j = s.f_j
        self.n_j = s.n_j
        self.l_j = s.l_j
        self.nj = len(s.l_j)

        self.data = s.data

        # Below are things which are not really used all that much,
        # i.e. shouldn't generally be necessary.  Maybe we can make a system
        # involving dictionaries for these "optional" parameters
        
        # Required by print_info
        self.rcutfilter = s.rcutfilter
        self.rcore = s.rcore
        self.basis = s.basis # we don't need niAO if we use this instead
        # Can also get rid of the phit_j splines if need be

        self.N0_p = s.N0_p # req. by estimate_magnetic_moments
        self.nabla_iiv = s.nabla_iiv  # req. by lrtddft

        # XAS stuff
        self.phicorehole_g = s.phicorehole_g # should be optional
        if s.phicorehole_g is not None:
            self.A_ci = s.A_ci # oscillator strengths

        # Required to get all electron density
        self.beta = s.beta
        self.rcut_j = s.rcut_j
        self.ng = s.ng

        self.tauct = s.tauct # required by TPSS, MGGA

        self.Delta_Lii = s.Delta_Lii # required with external potential

        self.B_ii = s.B_ii # required for exact inverse overlap operator
        self.dC_ii = s.dC_ii # required by time-prop tddft with apply_inverse

        # Required by exx
        self.X_p = s.X_p
        self.ExxC = s.ExxC

        # Required by electrostatic correction
        self.dEH0 = s.dEH0
        self.dEH_p = s.dEH_p

        # Required by utilities/kspot.py (AllElectronPotential)
        self.g_lg = s.g_lg
        
        # Probably empty dictionary, required by GLLB
        self.extra_xc_data = s.extra_xc_data


class Setup(BaseSetup):
    """Attributes:

    ========== =====================================================
    Name       Description
    ========== =====================================================
    ``Z``      Charge
    ``type``   Type-name of setup (eg. 'paw')
    ``symbol`` Chemical element label (eg. 'Mg')
    ``xcname`` Name of xc
    ``data``   Container class for information on the the atom, eg.
               Nc, Nv, n_j, l_j, f_j, eps_j, rcut_j.
               It defines the radial grid by ng and beta, from which
               r_g = beta * arange(ng) / (ng - arange(ng)).
               It stores pt_jg, phit_jg, phi_jg, vbar_g
    ========== =====================================================


    Attributes for making PAW corrections

    ============= ==========================================================
    Name          Description
    ============= ==========================================================
    ``Delta0``    Constant in compensation charge expansion coeff.
    ``Delta_Lii`` Linear term in compensation charge expansion coeff.
    ``Delta_pL``  Packed version of ``Delta_Lii``.
    ``dO_ii``     Overlap coefficients
    ``B_ii``      Projector function overlaps B_ii = <pt_i | pt_i>
    ``dC_ii``     Inverse overlap coefficients
    ``E``         Reference total energy of atom
    ``M``         Constant correction to Coulomb energy
    ``M_p``       Linear correction to Coulomb energy
    ``M_pp``      2nd order correction to Coulomb energy and Exx energy
    ``Kc``        Core kinetic energy
    ``K_p``       Linear correction to kinetic energy
    ``ExxC``      Core Exx energy
    ``X_p``       Linear correction to Exx energy
    ``MB``        Constant correction due to vbar potential
    ``MB_p``      Linear correction due to vbar potential
    ``dEH0``      Constant correction due to average electrostatic potential
    ``dEH_p``     Linear correction due to average electrostatic potential
    ``I4_iip``    Correction to integrals over 4 all electron wave functions
    ``Nct``       Analytical integral of the pseudo core density ``nct``
    ============= ==========================================================

    It also has the attribute ``xc_correction`` which is an XCCorrection class
    instance capable of calculating the corrections due to the xc functional.


    Splines:

    ========== ============================================
    Name       Description
    ========== ============================================
    ``pt_j``   Projector functions
    ``phit_j`` Pseudo partial waves
    ``vbar``   vbar potential
    ``nct``    Pseudo core density
    ``ghat_l`` Compensation charge expansion functions
    ``tauct``  Pseudo core kinetic energy density
    ========== ============================================
    """
    def __init__(self, data, xc, lmax=0, basis=None):
        self.type = data.name
        
        self.HubU = None
        
        if not data.is_compatible(xc):
            raise ValueError('Cannot use %s setup with %s functional' %
                             (data.setupname, xc.get_setup_name()))
        
        self.symbol = symbol = data.symbol
        self.data = data

        self.Nc = data.Nc
        self.Nv = data.Nv
        self.Z = data.Z
        l_j = self.l_j = data.l_j
        n_j = self.n_j = data.n_j
        self.f_j = data.f_j
        self.eps_j = data.eps_j
        nj = self.nj = len(l_j)
        ng = self.ng = data.ng
        beta = self.beta = data.beta
        rcut_j = self.rcut_j = data.rcut_j

        self.ExxC = data.ExxC
        self.X_p = data.X_p

        pt_jg = data.pt_jg
        phit_jg = data.phit_jg
        phi_jg = data.phi_jg

        self.fingerprint = data.fingerprint
        self.filename = data.filename

        g = np.arange(ng, dtype=float)
        r_g = beta * g / (ng - g)
        dr_g = beta * ng / (ng - g)**2
        d2gdr2 = -2 * ng * beta / (beta + r_g)**3

        self.lmax = lmax

        # Find Fourier-filter cutoff radius:
        gcutfilter = data.get_max_projector_cutoff()
        self.rcutfilter = rcutfilter = r_g[gcutfilter]

        rcutmax = max(rcut_j)
        rcut2 = 2 * rcutmax
        gcut2 = 1 + int(rcut2 * ng / (rcut2 + beta))
        self.gcut2 = gcut2

        self.gcutmin = 1 + int(min(rcut_j) * ng / (min(rcut_j) + beta))

        ni = 0
        i = 0
        j = 0
        jlL_i = []
        for l, n in zip(l_j, n_j):
            for m in range(2 * l + 1):
                jlL_i.append((j, l, l**2 + m))
                i += 1
            j += 1
        ni = i
        self.ni = ni

        _np = ni * (ni + 1) // 2
        self.nq = nq = nj * (nj + 1) // 2

        lcut = max(l_j)
        if 2 * lcut < lmax:
            lcut = (lmax + 1) // 2
        self.lcut = lcut

        self.B_ii = self.calculate_projector_overlaps(r_g, dr_g, pt_jg)

        self.fcorehole = data.fcorehole
        self.lcorehole = data.lcorehole
        if data.phicorehole_g is not None:
            if self.lcorehole == 0:
                self.calculate_oscillator_strengths(r_g, dr_g, phi_jg)
            else:
                self.A_ci = None

        # Construct splines:
        self.vbar = Spline(0, rcutfilter, data.vbar_g, r_g, beta)

        rcore, nc_g, nct_g, nct = self.construct_core_densities(r_g, dr_g,
                                                                beta, data)
        self.rcore = rcore
        self.nct = nct

        # Construct splines for core kinetic energy density:
        tauct_g = data.tauct_g
        if tauct_g is None:
            tauct_g = np.zeros(ng)
        self.tauct = Spline(0, self.rcore, tauct_g, r_g, beta)

        self.pt_j = self.create_projectors(r_g, rcutfilter, beta)

        if basis is None:
            basis = self.create_basis_functions(phit_jg, beta, ng, rcut2,
                                                gcut2, r_g)
        phit_j = basis.tosplines()
        self.phit_j = phit_j
        self.basis = basis #?

        self.niAO = 0
        for phit in self.phit_j:
            l = phit.get_angular_momentum_number()
            self.niAO += 2 * l + 1

        r_g = r_g[:gcut2].copy()
        dr_g = dr_g[:gcut2].copy()
        phi_jg = np.array([phi_g[:gcut2].copy() for phi_g in phi_jg])
        phit_jg = np.array([phit_g[:gcut2].copy() for phit_g in phit_jg])
        self.nc_g = nc_g = nc_g[:gcut2].copy()
        self.nct_g = nct_g = nct_g[:gcut2].copy()
        vbar_g = data.vbar_g[:gcut2].copy()
        tauc_g = data.tauc_g[:gcut2].copy()

        extra_xc_data = dict(data.extra_xc_data)
        # Cut down the GLLB related extra data
        for key, item in extra_xc_data.iteritems():
            if len(item) == ng:
                extra_xc_data[key] = item[:gcut2].copy()
        self.extra_xc_data = extra_xc_data

        self.phicorehole_g = data.phicorehole_g
        if self.phicorehole_g is not None:
            self.phicorehole_g = self.phicorehole_g[:gcut2].copy()

        T_Lqp = self.calculate_T_Lqp(lcut, nq, _np, nj, jlL_i)
        (g_lg, n_qg, nt_qg, Delta_lq, self.Lmax, self.Delta_pL, Delta0, 
         self.N0_p) = self.get_compensation_charges(r_g, dr_g, phi_jg,
                                                    phit_jg, _np, T_Lqp)
        self.Delta0 = Delta0
        self.g_lg = g_lg

        # Solves the radial poisson equation for density n_g
        def H(n_g, l):
            yrrdr_g = np.zeros(gcut2)
            nrdr_g = n_g * r_g * dr_g
            hartree(l, nrdr_g, beta, ng, yrrdr_g)
            yrrdr_g *= r_g * dr_g
            return yrrdr_g

        wnc_g = H(nc_g, l=0)
        wnct_g = H(nct_g, l=0)

        self.wg_lg = wg_lg = [H(g_lg[l], l) for l in range(lmax + 1)]

        wn_lqg = [np.array([H(n_qg[q], l) for q in range(nq)])
                  for l in range(2 * lcut + 1)]
        wnt_lqg = [np.array([H(nt_qg[q], l) for q in range(nq)])
                   for l in range(2 * lcut + 1)]

        rdr_g = r_g * dr_g
        dv_g = r_g * rdr_g
        A = 0.5 * np.dot(nc_g, wnc_g)
        A -= sqrt(4 * pi) * self.Z * np.dot(rdr_g, nc_g)
        mct_g = nct_g + Delta0 * g_lg[0]
        wmct_g = wnct_g + Delta0 * wg_lg[0]
        A -= 0.5 * np.dot(mct_g, wmct_g)
        self.M = A
        self.MB = -np.dot(dv_g * nct_g, vbar_g)
        
        AB_q = -np.dot(nt_qg, dv_g * vbar_g)
        self.MB_p = np.dot(AB_q, T_Lqp[0])
        
        # Correction for average electrostatic potential:
        #
        #   dEH = dEH0 + dot(D_p, dEH_p)
        #
        self.dEH0 = sqrt(4 * pi) * (wnc_g - wmct_g -
                                    sqrt(4 * pi) * self.Z * r_g * dr_g).sum()
        dEh_q = (wn_lqg[0].sum(1) - wnt_lqg[0].sum(1) -
                 Delta_lq[0] * wg_lg[0].sum())
        self.dEH_p = np.dot(dEh_q, T_Lqp[0]) * sqrt(4 * pi)
        
        M_p, M_pp = self.calculate_coulomb_corrections(lcut, n_qg, wn_lqg,
                                                       lmax, Delta_lq,
                                                       wnt_lqg, g_lg, 
                                                       wg_lg, nt_qg,
                                                       _np, T_Lqp, nc_g,
                                                       wnc_g, rdr_g, mct_g,
                                                       wmct_g)
        self.M_p = M_p
        self.M_pp = M_pp

        if xc.type == 'GLLB':
            if 'core_f' in self.extra_xc_data:
                self.wnt_lqg = wnt_lqg
                self.wn_lqg = wn_lqg
                self.fc_j = self.extra_xc_data['core_f']
                self.lc_j = self.extra_xc_data['core_l']
                self.njcore = len(self.lc_j)
                print self.extra_xc_data['core_states'].shape
                if self.njcore > 0:
                    self.uc_jg = self.extra_xc_data['core_states'].reshape((self.njcore, -1))
                    self.uc_jg = self.uc_jg[:, :gcut2]
                self.phi_jg = phi_jg
            
        self.Kc = data.e_kinetic_core - data.e_kinetic
        self.M -= data.e_electrostatic
        self.E = data.e_total

        Delta0_ii = unpack(self.Delta_pL[:, 0].copy())
        self.dO_ii = data.get_overlap_correction(Delta0_ii)
        self.dC_ii = self.get_inverse_overlap_coefficients(self.B_ii, self.dO_ii)
        
        self.Delta_Lii = np.zeros((ni, ni, self.Lmax)) # XXX index order
        for L in range(self.Lmax):
            self.Delta_Lii[:, :, L] = unpack(self.Delta_pL[:, L].copy())

        self.Nct = data.get_smooth_core_density_integral(Delta0)
        self.K_p = data.get_linear_kinetic_correction(T_Lqp[0])
        
        r = 0.02 * rcut2 * np.arange(51, dtype=float)
        alpha = data.rcgauss**-2
        self.ghat_l = data.get_ghat(lmax, alpha, r, rcut2)
        self.rcgauss = data.rcgauss
        #self.rcutcomp = sqrt(10) * rcgauss # ??? XXX Not used for anything
        
        rgd = RadialGridDescriptor(r_g, dr_g)
        self.xc_correction = data.get_xc_correction(rgd, xc, gcut2, lcut)
        self.nabla_iiv = self.get_derivative_integrals(rgd, phi_jg, phit_jg)

    def calculate_coulomb_corrections(self, lcut, n_qg, wn_lqg,
                                      lmax, Delta_lq, wnt_lqg,
                                      g_lg, wg_lg, nt_qg, _np, T_Lqp,
                                      nc_g, wnc_g, rdr_g, mct_g, wmct_g):
        # Can we reduce the excessive parameter passing?
        A_q = 0.5 * (np.dot(wn_lqg[0], nc_g) + np.dot(n_qg, wnc_g))
        A_q -= sqrt(4 * pi) * self.Z * np.dot(n_qg, rdr_g)
        A_q -= 0.5 * (np.dot(wnt_lqg[0], mct_g) + np.dot(nt_qg, wmct_g))
        A_q -= 0.5 * (np.dot(mct_g, wg_lg[0])
                      + np.dot(g_lg[0], wmct_g)) * Delta_lq[0]
        M_p = np.dot(A_q, T_Lqp[0])

        A_lqq = []
        for l in range(2 * lcut + 1):
            A_qq = 0.5 * np.dot(n_qg, np.transpose(wn_lqg[l]))
            A_qq -= 0.5 * np.dot(nt_qg, np.transpose(wnt_lqg[l]))
            if l <= lmax:
                A_qq -= 0.5 * np.outer(Delta_lq[l],
                                        np.dot(wnt_lqg[l], g_lg[l]))
                A_qq -= 0.5 * np.outer(np.dot(nt_qg, wg_lg[l]), Delta_lq[l])
                A_qq -= 0.5 * np.dot(g_lg[l], wg_lg[l]) * \
                        np.outer(Delta_lq[l], Delta_lq[l])
            A_lqq.append(A_qq)

        M_pp = np.zeros((_np, _np))
        L = 0
        for l in range(2 * lcut + 1):
            for m in range(2 * l + 1):
                M_pp += np.dot(np.transpose(T_Lqp[L]),
                               np.dot(A_lqq[l], T_Lqp[L]))
                L += 1

        return M_p, M_pp

    def create_projectors(self, r_g, rcut, beta):
        pt_j = []
        for j, pt_g in enumerate(self.data.pt_jg):
            l = self.l_j[j]
            pt_j.append(Spline(l, rcut, pt_g, r_g, beta))
        return pt_j

    def get_inverse_overlap_coefficients(self, B_ii, dO_ii):
        ni = len(B_ii)
        xO_ii = np.dot(B_ii, dO_ii)
        return -np.dot(dO_ii, np.linalg.inv(np.identity(ni) + xO_ii))

    def calculate_T_Lqp(self, lcut, nq, _np, nj, jlL_i):
        Lcut = (2 * lcut + 1)**2
        T_Lqp = np.zeros((Lcut, nq, _np))
        p = 0
        i1 = 0
        for j1, l1, L1 in jlL_i:
            for j2, l2, L2 in jlL_i[i1:]:
                if j1 < j2:
                    q = j2 + j1 * nj - j1 * (j1 + 1) // 2
                else:
                    q = j1 + j2 * nj - j2 * (j2 + 1) // 2
                T_Lqp[:, q, p] = G_LLL[L1, L2, :Lcut]
                p += 1
            i1 += 1
        return T_Lqp
    
    def calculate_projector_overlaps(self, r_g, dr_g, pt_jg):
        """Compute projector function overlaps B_ii = <pt_i | pt_i>."""
        nj = len(pt_jg)
        B_jj = np.zeros((nj, nj))
        for j1, pt1_g in enumerate(pt_jg):
            for j2, pt2_g in enumerate(pt_jg):
                B_jj[j1, j2] = np.dot(r_g**2 * dr_g, pt1_g * pt2_g)
        B_ii = np.zeros((self.ni, self.ni))
        i1 = 0
        for j1, l1 in enumerate(self.l_j):
            for m1 in range(2 * l1 + 1):
                i2 = 0
                for j2, l2 in enumerate(self.l_j):
                    for m2 in range(2 * l2 + 1):
                        if l1 == l2 and m1 == m2:
                            B_ii[i1, i2] = B_jj[j1, j2]
                        i2 += 1
                i1 += 1
        return B_ii

    def get_compensation_charges(self, r_g, dr_g, phi_jg, phit_jg, _np, T_Lqp):
        lmax = self.lmax
        gcut2 = self.gcut2
        nq = self.nq

        g_lg = self.data.create_compensation_charge_functions(lmax, r_g, dr_g)
        
        n_qg = np.zeros((nq, gcut2))
        nt_qg = np.zeros((nq, gcut2))
        q = 0 # q: common index for j1, j2
        for j1 in range(self.nj):
            for j2 in range(j1, self.nj):
                n_qg[q] = phi_jg[j1] * phi_jg[j2]
                nt_qg[q] = phit_jg[j1] * phit_jg[j2]
                q += 1
        
        gcutmin = self.gcutmin
        self.lq = np.dot(n_qg[:, :gcutmin], r_g[:gcutmin]**2 * dr_g[:gcutmin])

        Delta_lq = np.zeros((lmax + 1, nq))
        for l in range(lmax + 1):
            Delta_lq[l] = np.dot(n_qg - nt_qg, r_g**(2 + l) * dr_g)

        Lmax = (lmax + 1)**2
        Delta_pL = np.zeros((_np, Lmax))
        for l in range(lmax + 1):
            L = l**2
            for m in range(2 * l + 1):
                delta_p = np.dot(Delta_lq[l], T_Lqp[L + m])
                Delta_pL[:, L + m] = delta_p

        Delta0 = np.dot(self.nc_g - self.nct_g,
                        r_g**2 * dr_g) - self.Z / sqrt(4 * pi)

        # Electron density inside augmentation sphere.  Used for estimating
        # atomic magnetic moment:
        rcutmax = max(self.rcut_j)
        gcutmax = int(round(rcutmax * self.ng / (rcutmax + self.beta)))
        N0_q = np.dot(n_qg[:, :gcutmax], (r_g**2 * dr_g)[:gcutmax])
        N0_p = np.dot(N0_q, T_Lqp[0]) * sqrt(4 * pi)

        return g_lg, n_qg, nt_qg, Delta_lq, Lmax, Delta_pL, Delta0, N0_p

    def get_derivative_integrals(self, rgd, phi_jg, phit_jg):
        """Calculate PAW-correction matrix elements of nabla.

        ::
        
          /  _       _  d       _     ~   _  d   ~   _
          | dr [phi (r) -- phi (r) - phi (r) -- phi (r)]
          /        1    dx    2         1    dx    2

        and similar for y and z."""

        if extra_parameters.get('fprojectors'):
            return None
        
        r_g = rgd.r_g
        dr_g = rgd.dr_g
        nabla_iiv = np.empty((self.ni, self.ni, 3))
        i1 = 0
        for j1 in range(self.nj):
            l1 = self.l_j[j1]
            nm1 = 2 * l1 + 1
            i2 = 0
            for j2 in range(self.nj):
                l2 = self.l_j[j2]
                nm2 = 2 * l2 + 1
                f1f2or = np.dot(phi_jg[j1] * phi_jg[j2] -
                                phit_jg[j1] * phit_jg[j2], r_g * dr_g)
                dphidr_g = np.empty_like(phi_jg[j2])
                rgd.derivative(phi_jg[j2], dphidr_g)
                dphitdr_g = np.empty_like(phit_jg[j2])
                rgd.derivative(phit_jg[j2], dphitdr_g)
                f1df2dr = np.dot(phi_jg[j1] * dphidr_g -
                                 phit_jg[j1] * dphitdr_g, r_g**2 * dr_g)
                for v in range(3):
                    Lv = 1 + (v + 2) % 3
                    nabla_iiv[i1:i1 + nm1, i2:i2 + nm2, v] = (
                        (4 * pi / 3)**0.5 * (f1df2dr - l2 * f1f2or) *
                        G_LLL[Lv, l2**2:l2**2 + nm2, l1**2:l1**2 + nm1].T +
                        f1f2or *
                        Y_LLv[l1**2:l1**2 + nm1, l2**2:l2**2 + nm2, v])
                i2 += nm2
            i1 += nm1
        return nabla_iiv

    def construct_core_densities(self, r_g, dr_g, beta, setupdata):
        rcore = self.data.find_core_density_cutoff(r_g, dr_g, setupdata.nc_g)
        nct = Spline(0, rcore, setupdata.nct_g, r_g, beta)
        return rcore, setupdata.nc_g, setupdata.nct_g, nct

    def create_basis_functions(self, phit_jg, beta, ng, rcut2, gcut2, r_g):
        # Cutoff for atomic orbitals used for initial guess:
        rcut3 = 8.0  # XXXXX Should depend on the size of the atom!
        gcut3 = 1 + int(rcut3 * ng / (rcut3 + beta))

        # We cut off the wave functions smoothly at rcut3 by the
        # following replacement:
        #
        #            /
        #           | f(r),                                   r < rcut2
        #  f(r) <- <  f(r) - a(r) f(rcut3) - b(r) f'(rcut3),  rcut2 < r < rcut3
        #           | 0,                                      r > rcut3
        #            \
        #
        # where a(r) and b(r) are 4. order polynomials:
        #
        #  a(rcut2) = 0,  a'(rcut2) = 0,  a''(rcut2) = 0,
        #  a(rcut3) = 1, a'(rcut3) = 0
        #  b(rcut2) = 0, b'(rcut2) = 0, b''(rcut2) = 0,
        #  b(rcut3) = 0, b'(rcut3) = 1
        #
        x = (r_g[gcut2:gcut3] - rcut2) / (rcut3 - rcut2)
        a_g = 4 * x**3 * (1 - 0.75 * x)
        b_g = x**3 * (x - 1) * (rcut3 - rcut2)

        class PartialWaveBasis(Basis): # yuckkk
            def __init__(self, symbol, phit_j):
                Basis.__init__(self, symbol, 'partial-waves', readxml=False)
                self.phit_j = phit_j
                
            def tosplines(self):
                return self.phit_j

            def get_description(self):
                template = 'Using partial waves for %s as LCAO basis'
                string = template % self.symbol
                return string

        phit_j = []
        for j, phit_g in enumerate(phit_jg):
            if self.n_j[j] > 0:
                l = self.l_j[j]
                phit = phit_g[gcut3]
                dphitdr = ((phit - phit_g[gcut3 - 1]) /
                           (r_g[gcut3] - r_g[gcut3 - 1]))
                phit_g[gcut2:gcut3] -= phit * a_g + dphitdr * b_g
                phit_g[gcut3:] = 0.0
                phit_j.append(Spline(l, rcut3, phit_g, r_g, beta, points=100))
        basis = PartialWaveBasis(self.symbol, phit_j)
        return basis

    def calculate_oscillator_strengths(self, r_g, dr_g, phi_jg):
        # XXX implement oscillator strengths for lcorehole != 0
        assert(self.lcorehole == 0)
        self.A_ci = np.zeros((3, self.ni))
        nj = len(phi_jg)
        i = 0
        for j in range(nj):
            l = self.l_j[j]
            if l == 1:
                a = np.dot(r_g**3 * dr_g, phi_jg[j] * self.data.phicorehole_g)

                for m in range(3):
                    c = (m + 1) % 3
                    self.A_ci[c, i] = a
                    i += 1
            else:
                i += 2 * l + 1
        assert i == self.ni


class Setups(list):
    """Collection of Setup objects. One for each distinct atom.

    Non-distinct atoms are those with the same atomic number, setup, and basis.

    Class attributes:
    
    ``nvalence``    Number of valence electrons.
    ``nao``         Number of atomic orbitals.
    ``Eref``        Reference energy.
    ``core_charge`` Core hole charge.
    """

    def __init__(self, Z_a, setup_types, basis_sets, lmax, xc,
                 world=None):
        list.__init__(self)
        symbols = [chemical_symbols[Z] for Z in Z_a]
        type_a = types2atomtypes(symbols, setup_types, default='paw')
        basis_a = types2atomtypes(symbols, basis_sets, default=None)
        
        # Construct necessary PAW-setup objects:
        self.setups = {}
        natoms = {}
        self.id_a = zip(Z_a, type_a, basis_a)
        for id in self.id_a:
            setup = self.setups.get(id)
            if setup is None:
                Z, type, basis = id
                symbol = chemical_symbols[Z]
                setupdata = None
                if not isinstance(type, str):
                    setupdata = type
                # Basis may be None (meaning that the setup decides), a string
                # (meaning we load the basis set now from a file) or an actual
                # pre-created Basis object (meaning we just pass it along)
                if isinstance(basis, str):
                    basis = Basis(symbol, basis, world=world)
                setup = create_setup(symbol, xc, lmax, type,
                                     basis, setupdata=setupdata, world=world)
                self.setups[id] = setup
                natoms[id] = 0
            natoms[id] += 1
            self.append(setup)

        # Sum up ...
        self.nvalence = 0       # number of valence electrons
        self.nao = 0            # number of atomic orbitals
        self.Eref = 0.0         # reference energy
        self.core_charge = 0.0  # core hole charge
        for id, setup in self.setups.items():
            n = natoms[id]
            self.Eref += n * setup.E
            self.core_charge += n * (setup.Z - setup.Nv - setup.Nc)
            self.nvalence += n * setup.Nv
            self.nao += n * setup.niAO

    def set_symmetry(self, symmetry):
        """Find rotation matrices for spherical harmonics."""
        R_slmm = []
        for op_cc in symmetry.op_scc:
            op_vv = np.dot(np.linalg.inv(symmetry.cell_cv),
                           np.dot(op_cc, symmetry.cell_cv))
            R_slmm.append([rotation(l, op_vv) for l in range(4)])
        
        for setup in self.setups.values():
            setup.calculate_rotations(R_slmm)


def types2atomtypes(symbols, types, default):
    """Map a types identifier to a list with a type id for each atom.
    
    types can be a single str, or a dictionary mapping chemical
    symbols and/or atom numbers to a type identifier.
    If both a symbol key and atomnumber key relates to the same atom, then
    the atomnumber key is dominant.

    If types is a dictionary and contains None, this will be used as default
    type, otherwize input arg ``default`` is used as default.
    """
    natoms =  len(symbols)
    if isinstance(types, str):
        return [types] * natoms

    # If present, None will map to the default type, else use the input default
    type_a = [types.get(None, default)] * natoms

    # First symbols ...
    for symbol, type in types.items():
        if isinstance(symbol, str):
            for a, symbol2 in enumerate(symbols):
                if symbol == symbol2:
                    type_a[a] = type

    # and then atom indices
    for a, type in types.items():
        if isinstance(a, int):
            type_a[a] = type

    return type_a

