def agts(queue):
    queue.add('neb/neb1.py', ncpus=8)
    queue.add('aluminium/Al_fcc.py', ncpus=8)
    queue.add('aluminium/Al_fcc_convergence.py', ncpus=8)
    queue.add('diffusion/initial.py', ncpus=8)
    sol = queue.add('diffusion/solution.py', ncpus=8)
    queue.add('diffusion/densitydiff.py', deps=[sol])
    h2o = queue.add('vibrations/h2o.py', ncpus=8)
    queue.add('vibrations/H2O_vib.py', ncpus=8, deps=[h2o])
    na = queue.add('band_structure/Na_band.py', ncpus=8)
    queue.add('band_structure/plot_band.py', deps=[na])
    si = queue.add('wannier/si.py', ncpus=8)
    queue.add('wannier/wannier-si.py', deps=[si])
    benzene = queue.add('wannier/benzene.py', ncpus=8)
    queue.add('wannier/wannier-benzene.py', deps=[benzene])
    queue.add('lrtddft/ground_state.py', ncpus=8)
    queue.add('transport/pt_h2_tb_transport.py', ncpus=8)
    queue.add('transport/pt_h2_transport.py', ncpus=8)
    queue.add('wavefunctions/CO.py', ncpus=8)
    ferro = queue.add('iron/ferro.py', ncpus=8)
    anti = queue.add('iron/anti.py', ncpus=8)
    non = queue.add('iron/non.py', ncpus=8)
    queue.add('iron/PBE.py', deps=[ferro, anti, non])