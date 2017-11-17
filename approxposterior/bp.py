"""

Bayesian Posterior estimation routines written in pure python leveraging
Dan Forman-Mackey's george Gaussian Process implementation and emcee.

August 2017

@author: David P. Fleming [University of Washington, Seattle]
@email: dflemin3 (at) uw (dot) edu

A meh implementation of Kandasamy et al. (2015)'s BAPE model.

"""

from __future__ import (print_function, division, absolute_import, u
                        nicode_literals)

# Tell module what it's allowed to import
__all__ = ["ApproxPosterior"]

import numpy as np
import george
from george import kernels
import emcee
import corner
from scipy.optimize import minimize, basinhopping
from sklearn.neighbors import KernelDensity
from sklearn.model_selection import GridSearchCV
from sklearn.mixture import GaussianMixture
import corner
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm


def rosenbrock_log_likelihood(x):
    """
    2D Rosenbrock function as a log likelihood following Wang & Li (2017)

    Parameters
    ----------
    x : array

    Returns
    -------
    l : float
        likelihood
    """

    x = np.array(x)
    if x.ndim > 1:
        x1 = x[:,0]
        x2 = x[:,1]
    else:
        x1 = x[0]
        x2 = x[1]

    return -0.01*(x1 - 1.0)**2 - (x1*x1 - x2)**2
# end function

def log_rb_prior(x1, x2):
    """
    Uniform log prior for the 2D Rosenbrock likelihood following Wang & Li (2017)
    where the prior pi(x) is a uniform distribution over [-5, 5] x [-5, 5]

    Parameters
    ----------
    x : array

    Returns
    -------
    l : float
        log prior
    """
    if (x1 > 5) or (x1 < -5) or (x2 > 5) or (x2 < -5):
        return -np.inf

    # All parameters in range equally likely
    return 0.0
log_rb_prior = np.vectorize(log_rb_prior)
# end function


def log_rosenbrock_prior(x):
    """
    Uniform log prior for the 2D Rosenbrock likelihood following Wang & Li (2017)
    where the prior pi(x) is a uniform distribution over [-5, 5] x [-5, 5]

    Parameters
    ----------
    x : array

    Returns
    -------
    l : float
        log prior
    """

    x = np.array(x)
    if x.ndim > 1:
        x1 = x[:,0]
        x2 = x[:,1]
    else:
        x1 = x[0]
        x2 = x[1]

    return log_rb_prior(x1, x2)
# end function


def rosenbrock_prior(x):
    """
    Uniform prior for the 2D Rosenbrock likelihood following Wang & Li (2017)
    where the prior pi(x) is a uniform distribution over [-5, 5] x [-5, 5]

    Parameters
    ----------
    x : array

    Returns
    -------
    l : float
        log prior
    """

    return np.exp(log_rosenbrock_prior(x))
# end function


def rosenbrock_sample(n):
    """
    Sample N points from the prior pi(x) is a uniform distribution over
    [-5, 5] x [-5, 5]

    Parameters
    ----------
    n : int
        Number of samples

    Returns
    -------
    sample : floats
        n x 2 array of floats samples from the prior
    """

    return np.random.uniform(low=-5, high=5, size=(n,2)).squeeze()
# end function


def plot_gp(gp, theta, y, xmin=-5, xmax=5, ymin=-5, ymax=5, n=100,
            return_var=False, save_plot=None, log=False, **kw):
    """
    DOCS
    """

    xx = np.linspace(xmin, xmax, n)
    yy = np.linspace(ymin, ymax, n)

    zz = np.zeros((len(xx),len(yy)))
    for ii in range(len(xx)):
        for jj in range(len(yy)):
            mu, var = gp.predict(y, np.array([xx[ii],yy[jj]]).reshape(1,-1), return_var=return_var)
            if return_var:
                zz[ii,jj] = var
            else:
                zz[ii,jj] = mu

    if log:
        if not return_var:
            zz = np.fabs(zz)
            #norm = LogNorm(vmin=1.0e-4, vmax=1.0e2)
        if return_var:

            zz[zz < 1.0e-6] = 1.0e-1
            #norm = LogNorm(vmin=1.0e-1, vmax=1.0e5)

        norm = LogNorm(vmin=zz.min(), vmax=zz.max())


    # Plot what the GP thinks the function looks like
    fig, ax = plt.subplots(**kw)
    im = ax.pcolormesh(xx, yy, zz.T, norm=norm)
    cb = fig.colorbar(im)

    if return_var:
        cb.set_label("Variance", labelpad=20, rotation=270)
    else:
        cb.set_label("|Mean|", labelpad=20, rotation=270)


    # Scatter plot where the points are
    ax.scatter(theta[:,0], theta[:,1], color="red")

    # Format
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)

    if save_plot is not None:
        fig.savefig(save_plot, bbox_inches="tight")

    return fig, ax
# end function


class ApproxPosterior(object):
    """
    Class to approximate the posterior distributions using either the
    Bayesian Active Posterior Estimation (BAPE) by Kandasamy et al. 2015 or the
    AGP (Adaptive Gaussian Process) by XXX et al.
    """

    def __init__(self, gp, prior, loglike, algorithm="BAPE"):
        """
        Initializer.

        Parameters
        ----------
        gp : george.GP
            Gaussian process object
        prior : function
            Defines the log prior over the input features.
        loglike : function
            Defines the log likelihood function.  In this function, it is assumed
            that the forward model is evaluated on the input theta and the output
            is used to evaluate the log likelihood.
        algorithm : str (optional)
            Which utility function to use.  Defaults to BAPE.

        Returns
        -------
        None
        """

        self.gp = gp
        self.prior = prior
        self._loglike = loglike
        self.algorithm = algorithm

        # Assign utility function
        if self.algorithm.lower() == "bape":
            self.utility = BAPE_utility
        elif self.algorithm.lower() == "agp":
            self.utility = AGP_utility
        else:
            raise IOError("Invalid algorithm. Valid options: BAPE, AGP.")

        # Initial approximate posteriors are the prior
        self.posterior = prior
        self.__prev_posterior = prior

    # end function


    def _sample(self, theta):
        """
        Draw a sample from the approximate posterior
        DOCS
        """
        theta_test = np.array(theta).reshape(1,-1)

        # Sometimes the input values can be crazy
        if np.isinf(theta_test).any() or np.isnan(theta_test).any() or not np.isfinite(theta_test.sum()):
            return -np.inf

        res = self.gp.sample_conditional(self.__y, theta_test) + self.posterior(theta_test)

        # Catch NaNs because they can happen for I don't know why reasons
        if np.isnan(res):
            return -np.inf
        else:
            return res
    # end function


    def run(self, theta, y, m=10, M=10000, nmax=2, Dmax=0.1, kmax=5, sampler=None,
            sim_annealing=False, **kw):
        """
        Core algorithm.

        Parameters
        ----------
        theta : array
            Input features (n_samples x n_features)
        y : array
            Input result of forward model (n_samples,)
        m : int (optional)
            Number of new input features to find each iteration.  Defaults to 10.
        M : int (optional)
            Number of MCMC steps to sample GP to estimate the approximate posterior.
            Defaults to 10^4.
        nmax : int (optional)
            Maximum number of iterations.  Defaults to 2 for testing.
        Dmax : float (optional)
            Maximum change in KL divergence for convergence checking.  Defaults to 0.1.
        kmax : int (optional)
            Maximum number of iterators such that if the change in KL divergence is
            less than Dmax for kmax iterators, the algorithm is considered
            converged and terminates.  Defaults to 5.
        sample : emcee.EnsembleSampler (optional)
            emcee sampler object.  Defaults to None and is initialized internally.
        sim_annealing : bool (optional)
            Whether or not to minimize utility function using simulated annealing.
            Defaults to False.

        Returns
        -------
        None
        """

        # Store theta, y
        self.__theta = theta
        self.__y = y

        # Main loop
        for n in range(nmax):

            # 1) Find m new points by maximizing utility function
            for ii in range(m):
                theta_t = minimize_objective(self.utility, self.__y, self.gp,
                                             sample_fn=None,
                                             sim_annealing=sim_annealing,
                                             **kw)

                # 2) Query oracle at new points, theta_t
                y_t = self._loglike(theta_t) - self.posterior(theta_t)

                # Join theta, y arrays
                self.__theta = np.concatenate([self.__theta, theta_t])
                self.__y = np.concatenate([self.__y, y_t])

                # 3) Refit GP
                # Guess the bandwidth following Kandasamy et al. (2015)'s suggestion
                bandwidth = 5 * np.power(len(self.__y),(-1.0/self.__theta.shape[-1]))

                # Create the GP conditioned on {theta_n, log(L_n * p_n)}
                kernel = np.var(self.__y) * kernels.ExpSquaredKernel(bandwidth, ndim=self.__theta.shape[-1])
                self.gp = george.GP(kernel)
                self.gp.compute(self.__theta)

                # Optimize gp hyperparameters
                optimize_gp(self.gp, self.__y)

            # Done adding new design points
            fig, _ = plot_gp(self.gp, self.__theta, self.__y, return_var=False,
                    save_plot="gp_mu_iter_%d.png" % n, log=True)
            plt.close(fig)

            # Done adding new design points
            fig, _ = plot_gp(self.gp, self.__theta, self.__y, return_var=True,
                    save_plot="gp_var_iter_%d.png" % n, log=True)
            plt.close(fig)

            # GP updated: run sampler to obtain new posterior conditioned on (theta_n, log(L_t)*p_n)

            # Use emcee to obtain approximate posterior
            ndim = self.__theta.shape[-1]
            nwalk = 10 * ndim
            nsteps = M

            # Initial guess (random over interval)
            p0 = [np.random.uniform(low=-5, high=5, size=ndim) for j in range(nwalk)]
            #p0 = [np.random.rand(ndim) for j in range(nwalk)]
            params = ["x%d" % jj for jj in range(ndim)]
            sampler = emcee.EnsembleSampler(nwalk, ndim, self._sample)
            for i, result in enumerate(sampler.sample(p0, iterations=nsteps)):
                print("%d/%d" % (i+1, nsteps))

            print("emcee finished!")

            #fig = corner.corner(sampler.flatchain, quantiles=[0.16, 0.5, 0.84],
            #                    plot_contours=False, bins="auto");
            fig, ax = plt.subplots(figsize=(9,8))
            corner.hist2d(sampler.flatchain[:,0], sampler.flatchain[:,1], ax=ax,
                                plot_contours=False, no_fill_contours=True,
                                plot_density=True)
            ax.scatter(self.__theta[:,0], self.__theta[:,1])
            ax.set_xlim(-5,5)
            ax.set_ylim(-5,5)
            fig.savefig("posterior_%d.png" % n)
            #plt.show()

            # Make new posterior function via a Gaussian Mixure model approximation
            # to the approximate posterior. Seems legit
            # Fit some GMMs!
            # sklean hates infs, Nans, big numbers
            mask = (~np.isnan(sampler.flatchain).any(axis=1)) & (~np.isinf(sampler.flatchain).any(axis=1))
            bic = []
            lowest_bic = 1.0e10
            best_gmm = None
            gmm = GaussianMixture()
            for n in range(5,10):
                gmm.set_params(**{"n_components" : n, "covariance_type" : "full"})
                gmm.fit(sampler.flatchain[mask])
                bic.append(gmm.bic(sampler.flatchain[mask]))

                if bic[-1] < lowest_bic:
                    lowest_bic = bic[-1]
                    best_gmm = gmm

            # Refit GMM with the lowest bic
            GMM = best_gmm
            GMM.fit(sampler.flatchain[mask])
            #self.posterior = GMM.score_samples

# Test!
if __name__ == "__main__":

    # Define algorithm parameters
    m0 = 20 # Initialize size of training set
    m = 10  # Number of new points to find each iteration
    nmax = 10 # Maximum number of iterations
    M = int(1.0e2) # Number of MCMC steps to estimate approximate posterior
    Dmax = 0.1
    kmax = 5
    kw = {}

    # Choose m0 initial design points to initialize dataset
    theta = rosenbrock_sample(m0)
    y = rosenbrock_log_likelihood(theta) + log_rosenbrock_prior(theta)

    # 0) Initial GP fit
    # Guess the bandwidth following Kandasamy et al. (2015)'s suggestion
    bandwidth = 5 * np.power(len(y),(-1.0/theta.shape[-1]))

    # Create the GP conditioned on {theta_n, log(L_n / p_n)}
    kernel = np.var(y) * kernels.ExpSquaredKernel(bandwidth, ndim=theta.shape[-1])
    gp = george.GP(kernel)
    gp.compute(theta)

    # Optimize gp hyperparameters
    optimize_gp(gp, y)

    # Init object
    bp = ApproxPosterior(gp, prior=log_rosenbrock_prior,
                         loglike=rosenbrock_log_likelihood,
                         algorithm="agp")

    # Run this bastard
    bp.run(theta, y, m=m, M=M, nmax=nmax, Dmax=Dmax, kmax=kmax,
           sampler=None, sim_annealing=False, **kw)