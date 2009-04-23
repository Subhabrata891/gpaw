import numpy as np
from gpaw import GPAW
from gpaw.transport.tools import k2r_hs, get_hs, dagger, dot
from gpaw.utilities.lapack import inverse_general, inverse_symmetric
from gpaw.lcao.tools import get_realspace_hs

class LeadSelfEnergy:
    conv = 1e-8 # Convergence criteria for surface Green function
    
    def __init__(self, hs_dii, hs_dij, hs_dim, eta=1e-4):
        self.h_ii, self.s_ii = hs_dii # onsite principal layer
        self.h_ij, self.s_ij = hs_dij # coupling between principal layers
        self.h_im, self.s_im = hs_dim # coupling to the central region
        self.nbf = self.h_im.shape[1] # nbf for the scattering region
        self.eta = eta
        self.energy = None
        self.bias = 0
        self.sigma_mm = np.empty((self.nbf, self.nbf), complex)

    def __call__(self, energy):
        """Return self-energy (sigma) evaluated at specified energy."""
        if self.h_im.dtype == float:
            inv = inverse_symmetric
        if self.h_im.dtype == complex:
            inv = inverse_general
        self.energy = energy
        z = energy - self.bias + self.eta * 1.j           
        tau_im = z * self.s_im - self.h_im
        ginv = self.get_sgfinv(energy)
        inv(ginv)
        a_im = dot(ginv, tau_im)
        tau_mi = z * dagger(self.s_im) - dagger(self.h_im)
        self.sigma_mm[:] = dot(tau_mi, a_im)
        return self.sigma_mm

    def set_bias(self, bias):
        self.bias = bias
        
    def get_lambda(self, energy):
        """Return the lambda (aka Gamma) defined by i(S-S^d).

        Here S is the retarded selfenergy, and d denotes the hermitian
        conjugate.
        """
        sigma_mm = self(energy)
        return 1.j * (sigma_mm - dagger(sigma_mm))
        
    def get_sgfinv(self, energy):
        """The inverse of the retarded surface Green function"""
        if self.h_im.dtype == float:
            inv = inverse_symmetric
        if self.h_im.dtype == complex:
            inv = inverse_general
        z = energy - self.bias + self.eta * 1.0j
        
        v_00 = z * dagger(self.s_ii) - dagger(self.h_ii)
        v_11 = v_00.copy()
        v_10 = z * self.s_ij - self.h_ij
        v_01 = z * dagger(self.s_ij) - dagger(self.h_ij)
        delta = self.conv + 1
        n = 0
        while delta > self.conv:
            inv_v_11 = np.copy(v_11)
            inv(inv_v_11)
            a = dot(inv_v_11, v_01)
            b = dot(inv_v_11, v_10)
            v_01_dot_b = dot(v_01, b)
            v_00 -= v_01_dot_b
            v_11 -= dot(v_10, a)
            v_11 -= v_01_dot_b
            v_01 = -dot(v_01, a)
            v_10 = -dot(v_10, b)
            delta = np.abs(v_01).max()
            n += 1
        return v_00
    
class CellSelfEnergy:
    def __init__(self, h_skmm, s_kmm, kpts, td=2, eta=1e-4):
        self.h_skmm, self.s_kmm = h_skmm, s_kmm
        self.kpts = kpts
        self.bias = 0
        self.energy = None
        self.transport_direction = td
        ns = self.h_skmm.shape[0]
        nb = self.h_skmm.shape[-1]
        self.sigma = np.empty([ns, nb, nb], complex)
        self.sigma2 = np.empty([ns, nb, nb], complex)
        self.sigma3 = np.empty([ns, nb, nb], complex)
        self.initialize()
        
    def set_bias(self, bias):
        self.bias = bias
        
    def call2(self, energy):
        h_skmm, s_kmm = self.h_skmm, self.s_kmm
        h_mm, s_mm = self.h_smm, self.s_mm
        self.g_skmm = np.empty(self.h_skmm.shape, complex)
        self.g_smm = np.empty(self.h_smm.shape, complex)

        g_skmm, g_smm = self.g_skmm, self.g_smm
        ns = h_skmm.shape[0]
        nk = h_skmm.shape[1]
        kpts = self.kpts
        weight = [1./len(kpts)] * len(kpts)
        inv = inverse_general
        for s in range(ns):
            for k in range(nk):
                g_skmm[s, k] = energy * s_kmm[k] - h_skmm[s, k]
                inv(g_skmm[s, k])
            g_mm = get_realspace_hs(g_skmm, None, kpts, weight)
            inv(g_mm[s])
            self.sigma2[s] = energy * s_mm - h_mm - g_mm[s]
        return self.sigma2[0]

    def call3(self, energy):
        self.g_skmm3 = np.empty(self.h_skmm.shape, complex)
        self.g_spkmm3 = np.empty(self.h_spkmm.shape, complex)
        self.g_smm3 = np.empty(self.h_smm.shape, complex)
        ns, npk, nb = self.h_spkmm.shape[:3]
        g_stkmm = np.empty([ns, self.ntk, nb, nb], complex)
      
        npk = self.npk
        ntk = self.ntk
        id = self.tp_index

        inv = inverse_general
        for k in range(npk):
            for ik, i in zip(id[k], range(ntk)):
                g_stkmm[:, i] = energy * self.s_kmm[ik] - self.h_skmm[:, ik]
                for s in range(ns):
                    inv(g_stkmm[s, i])
            self.g_spkmm3[:, k] = k2r_hs(g_stkmm, None, self.t_kpts, self.t_weight)
     
        self.g_smm3 = k2r_hs(self.g_spkmm3, None, self.p_kpts, self.p_weight)
        g_mm = self.g_smm3.copy()
        
        for s in range(ns):
            inv(g_mm[s])
            self.sigma3[s] = energy * self.s_mm - self.h_smm - g_mm[s]
        return self.sigma3[0]
    
    def __call__(self, energy):
        ns, nk = self.h_spkmm.shape[:2]
        kpts = self.p_kpts
        weight = self.p_weight
        inv = inverse_general
        for k in range(nk):
            for s in range(ns):
                self.g_spkmm[s, k] = self.get_tdse(s, k, energy - self.bias)
        self.g_smm = k2r_hs(self.g_spkmm, None, kpts, weight)
        g_mm = self.g_smm.copy()
        
        for s in range(ns):
            inv(g_mm[s])
            #g_mm[s] = np.linalg.inv(self.g_smm[s])
            self.sigma[s] = (energy - self.bias) * self.s_mm - self.h_smm[s] \
                                                              - g_mm[s]
        return self.sigma

    def get_tdse(self, s, k, energy):
        sl = self.td_selfenergy_left
        sl.h_ii = self.h_spkmm[s, k]
        sl.s_ii = self.s_pkmm[k]
        sl.h_ij = self.h_spkcmm[s, k]
        sl.s_ij = self.s_pkcmm[k]
        sl.h_im = self.h_spkcmm[s, k]
        sl.s_im = self.s_pkcmm[k]

        sr = self.td_selfenergy_right
        sr.h_ii = self.h_spkmm[s, k]
        sr.s_ii = self.s_pkmm[k]
        sr.h_ij = self.h_spkcmm2[s, k]
        sr.s_ij = self.s_pkcmm2[k]
        sr.h_im = self.h_spkcmm2[s, k]
        sr.s_im = self.s_pkcmm2[k]
  
        sigma = sl(energy) + sr(energy)

        g_mm = energy * self.s_pkmm[k] - self.h_spkmm[s, k] - sigma
        #g_mm = energy * self.s_pkmm[k] - self.h_spkmm[s, k]
        #inverse_general(g_mm)
        g_mm = np.linalg.inv(g_mm) 
        return g_mm
        
    def get_lambda(self, energy):
        sigma = self.__call__(energy)
        return 1.j * (self.sigma[0] - dagger(self.sigma[0]))

    def divide_kpts(self, dim_type, dim_flag):
        td = self.transport_direction
        kpts = self.kpts
        t_kpts = []
        p_kpts = [kpts[0].copy()]
        p_kpts[0][td] = 0
        for kpt in kpts:
            if kpt[td] in t_kpts:
                pass
            else:
                t_kpts.append(kpt[td])
            p_kpt = kpt.copy()
            p_kpt[td] = 0.
            tmp = p_kpt - p_kpts
            tmp = np.sum(tmp, axis=1)
            if not tmp.all():
                pass
            else:
                p_kpts.append(p_kpt)
        self.t_kpts = np.zeros([len(t_kpts), 3])
        self.t_kpts[:, td] = t_kpts
        self.p_kpts = np.array(p_kpts)
        self.ntk = len(self.t_kpts)
        self.npk = len(self.p_kpts)
        self.t_weight = [ 1./ self.ntk] * self.ntk
        self.p_weight = [ 1./ self.npk] * self.npk

    def get_tp_index(self):
        self.tp_index = np.zeros([self.npk, self.ntk], int)
        td = self.transport_direction
        num = 0
        for kpt in self.kpts:
            t_kpts = self.t_kpts.copy()
            tmp = np.zeros([3])
            tmp[td] = kpt[td]
            t_kpts -= tmp
            t_kpts = np.sum(abs(t_kpts), axis=1)
            col_index = np.argmin(t_kpts)

            p_kpts = self.p_kpts.copy()
            tmp = kpt.copy()
            tmp[td] = 0
            p_kpts -= tmp
            p_kpts = np.sum(abs(p_kpts), axis=1)
            row_index = np.argmin(p_kpts)
            self.tp_index[row_index, col_index] = num
            num += 1
        
    def substract_p_hs(self):
        ntk = self.ntk
        npk = self.npk
        td = self.transport_direction
        ns, nk, nb = self.h_skmm.shape[:3]
        self.h_spkmm = np.empty([ns, npk, nb, nb], complex)
        self.h_spkcmm = np.empty([ns, npk, nb, nb], complex)
        self.h_spkcmm2 = np.empty([ns, npk, nb, nb], complex)
        self.s_pkmm = np.empty([npk, nb, nb], complex)
        self.s_pkcmm = np.empty([npk, nb, nb], complex)
        self.s_pkcmm2 = np.empty([npk, nb, nb], complex)
        
        id = self.tp_index
        kpts = self.t_kpts
        weight = self.t_weight
        positions = np.zeros([3, 3])
        positions[:, td] = np.array([0., 1., -1.])
        h_skmm = self.h_skmm
        s_kmm = self.s_kmm
        for i in range(npk):
            self.h_spkmm[:, i], self.s_pkmm[i] = k2r_hs(h_skmm[:, id[i]],
                                                        s_kmm[id[i]],
                                                        kpts,
                                                        weight,
                                                        R_c=positions[0])
            
            self.h_spkcmm[:, i], self.s_pkcmm[i] = k2r_hs(h_skmm[:, id[i]],
                                                          s_kmm[id[i]],
                                                          kpts,
                                                          weight,
                                                          R_c=positions[1])
            
            self.h_spkcmm2[:, i], self.s_pkcmm2[i] = k2r_hs(h_skmm[:, id[i]],
                                                            s_kmm[id[i]],
                                                            kpts,
                                                            weight,
                                                            R_c=positions[2])
      
    def initialize(self):
        dim = np.sum(abs(self.kpts), axis=0)
        dim_flag = np.empty([3], dtype=int)
        for i in range(3):
            if dim[i] == 0:
                dim_flag[i] = 0
            else:
                dim_flag[i] = 1
        dim_type =  np.sum(dim_flag)
        if dim_type == 1:
            pass
            #raise RuntimError('Wrong dimension for using env')
        elif dim_type == 2:
            td = self.transport_direction
            if dim_flag[td] != 1:
                raise RuntimeError('Wrong transport direction for env')
        self.divide_kpts(dim_type, dim_flag)
        self.get_tp_index()
        self.substract_p_hs()
        self.td_selfenergy_left = LeadSelfEnergy((self.h_spkmm[0,0],
                                                  self.s_pkmm[0]),
                                                 (self.h_spkcmm[0,0],
                                                  self.s_pkcmm[0]),
                                                 (self.h_spkcmm[0,0],
                                                  self.s_pkcmm[0]), 0)
        self.td_selfenergy_right = LeadSelfEnergy((self.h_spkmm[0,0],
                                                  self.s_pkmm[0]),
                                                 (self.h_spkcmm2[0,0],
                                                  self.s_pkcmm2[0]),
                                                 (self.h_spkcmm2[0,0],
                                                  self.s_pkcmm2[0]), 0)
        self.h_smm = np.sum(self.h_skmm, axis=1) / len(self.kpts)
        self.s_mm = np.sum(self.s_kmm, axis=0) / len(self.kpts) 
        self.g_spkmm = np.empty(self.h_spkmm.shape, self.h_spkmm.dtype)
        self.g_smm = np.empty(self.h_smm.shape, self.h_smm.dtype)
