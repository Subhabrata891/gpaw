qsub -A Gpaw -q prod -n 512 -t 90 --mode smp --env OMP_NUM_THREADS=1:GPAW_SETUP_PATH=$GPAW_SETUP_PATH:PYTHONPATH="${HOME}/gpaw:$PYTHONPATH":LD_LIBRARY_PATH="/bgsys/drivers/ppcfloor/gnu-linux/powerpc-bgp-linux/lib:$LD_LIBRARY_PATH" ${HOME}/gpaw/build/bin.linux-ppc64-2.5/gpaw-python ../Au_cluster.py --sl_diagonalize=5,5,64,4
