#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""

Test loading approxposterior and running the core algorithm for 1 iteration.

@author: David P. Fleming [University of Washington, Seattle], 2018
@email: dflemin3 (at) uw (dot) edu

"""

from __future__ import (print_function, division, absolute_import,
                        unicode_literals)


from approxposterior import bp, likelihood as lh
import numpy as np

def test_run():
    """
    Test the core approxposterior algorithm for 2 iterations.
    """

    # Define algorithm parameters
    m0 = 200                          # Initial size of training set
    m = 20                            # Number of new points to find each iteration
    nmax = 1                          # Maximum number of iterations
    M = int(5.0e3)                    # Number of MCMC steps to estimate approximate posterior
    Dmax = 0.1                        # KL-Divergence convergence limit
    kmax = 5                          # Number of iterations for Dmax convergence to kick in
    which_kernel = "ExpSquaredKernel" # Which Gaussian Process kernel to use
    bounds = ((-5,5), (-5,5))         # Prior bounds
    algorithm = "bape"                # Use the Kandasamy et al. (2015) formalism

    # Initialize object using the Wang & Li (2017) Rosenbrock function example
    ap = bp.ApproxPosterior(lnprior=lh.rosenbrock_lnprior,
                            lnlike=lh.rosenbrock_lnlike,
                            prior_sample=lh.rosenbrock_sample,
                            algorithm=algorithm)

    # Run!
    ap.run(m0=m0, m=m, M=M, nmax=nmax, Dmax=Dmax, kmax=kmax,
            sampler=None, bounds=bounds, which_kernel=which_kernel,
            n_kl_samples=100000, verbose=False, debug=False)

    # Ensure medians of chains are consistent with the true values
    x1_med, x2_med = np.median(ap.samplers[-1].flatchain[ap.iburns[-1]:], axis=0)

    diff_x1 = np.fabs(0.04 - x1_med)
    diff_x2 = np.fabs(1.29 - x2_med)

    # Differences between estimated and true medians must be less than
    # the true error bars
    err_msg = "Medians of marginal posteriors are incosistent with true values."
    assert((diff_x1 < 1.5) & (diff_x2 < 1.3)), err_msg

# end function
