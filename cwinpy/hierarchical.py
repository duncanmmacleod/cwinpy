"""
Classes for hierarchical parameter inference.
"""

from itertools import compress

import bilby
import numpy as np
from lintegrate import logtrapz
from scipy.interpolate import interp1d
from scipy.stats import expon, gaussian_kde, truncnorm

# allowed distributions and their required hyperparameters
DISTRIBUTION_REQUIREMENTS = {
    "exponential": ["mu"],
    "gaussian": ["mu", "sigma", "weight"],
    "deltafunction": ["peak"],
}


class BaseDistribution(object):
    """
    The base class for the distribution, as defined by a set of
    hyperparameters, that you want to fit.

    Parameters
    ----------
    name: str
        The parameter for which this distribution is the prior.
    disttype: str
        The type of distribution, e.g., 'exponential', 'gaussian'.
    hyperparameters: dict
        A dictionary of hyperparameters for the distribution with the keys
        giving the parameter names, and values giving their fixed value, or
        a :class:`bilby.core.prior.Prior` for values that are to be inferred.
    low: float
        The lower bound of the distribution
    high: float
        The upper bound of the distribution
    """

    def __init__(self, name, disttype, hyperparameters={}, low=-np.inf, high=np.inf):
        self.name = name  # the parameter name
        self.disttype = disttype
        self.hyperparameters = hyperparameters
        self.low = low
        self.high = high

        if self.low >= self.high:
            raise ValueError("Lower bound is higher than upper bound!")

    @property
    def disttype(self):
        return self._disttype

    @disttype.setter
    def disttype(self, disttype):
        if disttype.lower() not in DISTRIBUTION_REQUIREMENTS.keys():
            raise ValueError('Distribution name "{}" is not ' "known".format(disttype))
        else:
            self._disttype = disttype.lower()

    @property
    def hyperparameters(self):
        return self._hyperparameters

    @hyperparameters.setter
    def hyperparameters(self, hyperparameters):
        if isinstance(hyperparameters, dict):
            # check is contains the required parameter names
            for key in hyperparameters.keys():
                if key.lower() not in DISTRIBUTION_REQUIREMENTS[self.disttype]:
                    raise KeyError(
                        'Unknown parameter "{}" for distribution '
                        '"{}"'.format(key, self.disttype)
                    )
            self._hyperparameters = {
                key.lower(): value for key, value in hyperparameters.items()
            }
        else:
            raise TypeError("hyperparameters must be a dictionary")

        # set fixed values
        self.fixed = self._hyperparameters

    @property
    def parameters(self):
        return list(self.hyperparameters.keys())

    @property
    def values(self):
        return list(self.hyperparameters.values())

    @property
    def unpacked_parameters(self):
        params = []
        for key, value in self.hyperparameters.items():
            if isinstance(value, (list, np.ndarray)):
                for i in range(len(value)):
                    params.append("{0}{1:d}".format(key, i))
            else:
                params.append(key)
        return params

    @property
    def unpacked_values(self):
        values = []
        for key, value in self.hyperparameters.items():
            if isinstance(value, (list, np.ndarray)):
                for i in range(len(value)):
                    values.append(value[i])
            else:
                values.append(value)
        return values

    def __getitem__(self, item):
        if item.lower() in self.parameters:
            return self.hyperparameters[item.lower()]
        elif item.lower() in self.unpacked_parameters:
            return self.unpacked_values[self.unpacked_parameters.index(item.lower())]
        elif item.lower() in DISTRIBUTION_REQUIREMENTS[self.disttype]:
            return None
        else:
            raise KeyError('"{}" is not a parameter in this distribution'.format(item))

    def __setitem__(self, item, value):
        if item.lower() not in self.hyperparameters.keys():
            if item.lower() in DISTRIBUTION_REQUIREMENTS[self.disttype]:
                self._hyperparameters[item.lower()] = value
            else:
                raise KeyError(
                    '"{}" is not a parameter in this distribution'.format(item)
                )
        else:
            self._hyperparameters[item.lower()] = value

    @property
    def fixed(self):
        """
        Return a dictionary keyed to parameter names and with boolean values
        indicating whether the parameter is fixed (True), or to be inferred
        (False).
        """

        return self._fixed

    @fixed.setter
    def fixed(self, hyperparameters):
        self._fixed = dict()

        for param, value in hyperparameters.items():
            if isinstance(value, bilby.core.prior.Prior):
                self._fixed[param] = False
            elif isinstance(value, (list, np.ndarray)):
                self._fixed[param] = []
                for i in range(len(value)):
                    if isinstance(value[i], bilby.core.prior.Prior):
                        self._fixed[param].append(False)
                    elif isinstance(value[i], (int, float)):
                        self._fixed[param].append(True)
                    else:
                        raise TypeError("Hyperparameter type is not valid")
            elif isinstance(value, (int, float)):
                self._fixed[param] = True
            else:
                raise TypeError("Hyperparameter type is not valid")

    @property
    def unpacked_fixed(self):
        """
        Return a flattened version of ``fixed``, with multivalued parameters
        indexed.
        """

        fixed = dict()

        for param, value in zip(self.unpacked_parameters, self.unpacked_values):
            if isinstance(value, bilby.core.prior.Prior):
                fixed[param] = False
            elif isinstance(value, (int, float)):
                fixed[param] = True
            else:
                raise TypeError("Hyperparameter type is not valid")

        return fixed

    @property
    def unknown_parameters(self):
        """
        A list of the parameters that are to be inferred.
        """

        return list(
            compress(
                self.unpacked_parameters, ~np.array(list(self.unpacked_fixed.values()))
            )
        )

    @property
    def unknown_priors(self):
        """
        A list of the :class:`~bilby.core.prior.Prior`s for the parameters
        that are to be inferred.
        """

        return list(
            compress(
                self.unpacked_values, ~np.array(list(self.unpacked_fixed.values()))
            )
        )

    def log_pdf(self, value, hyperparameters):
        """
        The natural logarithm of the distribution's probability density
        function at the given value.

        Parameters
        ----------
        value: float
            The value at which to evaluate the probability.
        hyperparameters: dict
            A dictionary of the hyperparameter values that define the current
            state of the distribution.

        Returns
        -------
        lnpdf:
            The natural logarithm of the probability.
        """

        return np.nan

    def pdf(self, value, hyperparameters):
        """
        The distribution's probability density function at the given value.

        Parameters
        ----------
        value: float
            The value at which to evaluate the probability.
        hyperparameters: dict
            A dictionary of the hyperparameter values that define the current
            state of the distribution.

        Returns
        -------
        pdf:
            The probability density.
        """

        return np.exp(self.log_pdf(value, hyperparameters))

    def sample(self, hyperparameters, size=1):
        """
        Draw a sample from the distribution as defined by the given
        hyperparameters.

        Parameters
        ----------
        hyperparameters: dict
            A dictionary of the hyperparameter values that define the current
            state of the distribution.
        size: int
            The number of samples to draw from the distribution.

        Returns
        -------
        sample:
            A sample, or set of samples, from the distribution.
        """

        return None


class BoundedGaussianDistribution(BaseDistribution):
    """
    A distribution to define estimating the parameters of a (potentially
    multi-modal) bounded Gaussian distribution.

    Parameters
    ----------
    name: str
        See :class:`~cwinpy.hierarchical.BaseDistribution`
    mus: array_like
        A list of values of the means of each mode of the Gaussian.
    sigmas: array_like
        A list of values of the standard deviations of each mode of the
        Gaussian.
    weights: array_like
        A list of values of the weights (relative probabilities) of
        each mode. This will default to equal weights if not given. Note that
        for truncated distributions equal weight does not necessarily mean
        equal "height" of the mode.
    low: float
        The lower bound of the distribution (defaults to 0, i.e., only positive
        values are allowed)
    high: float
        The upper bound of the distribution (default to infinity)
    """

    def __init__(self, name, mus=[], sigmas=[], weights=None, low=0.0, high=np.inf):
        gaussianparameters = {"mu": [], "sigma": [], "weight": []}

        if isinstance(mus, (int, float, bilby.core.prior.Prior)):
            mus = [mus]
        elif not isinstance(mus, (list, np.ndarray)):
            raise TypeError("Unknown type for 'mus'")

        if isinstance(sigmas, (int, float, bilby.core.prior.Prior)):
            sigmas = [sigmas]
        elif not isinstance(sigmas, (list, np.ndarray)):
            raise TypeError("Unknown type for 'sigmas'")

        if weights is None:
            weights = [1] * len(mus)
        else:
            if isinstance(weights, (int, float, bilby.core.prior.Prior)):
                weights = [weights]
            elif not isinstance(weights, (list, np.ndarray)):
                raise TypeError("Unknown type for 'weights'")

        # set the number of modes
        self.nmodes = len(mus)

        if len(mus) != len(sigmas) or len(weights) != len(mus):
            raise ValueError("'mus', 'sigmas' and 'weights' must be the same " "length")

        if self.nmodes < 1:
            raise ValueError("Gaussian must have at least one mode")

        for i in range(self.nmodes):
            gaussianparameters["mu"].append(mus[i])
            gaussianparameters["sigma"].append(sigmas[i])
            gaussianparameters["weight"].append(weights[i])

        # initialise
        super().__init__(
            name, "gaussian", hyperparameters=gaussianparameters, low=low, high=high
        )

    def log_pdf(self, value, hyperparameters={}):
        """
        The natural logarithm of the pdf of a 1d (potentially multi-modal)
        Gaussian probability distribution.

        Parameters
        ----------
        value: float
            The value at which the probability is to be evaluated.
        hyperparameters: dict
            A dictionary containing the current values of the hyperparameters
            that need to be inferred.

        Returns
        -------
        logpdf:
            The natural logarithm of the probability density at the given
            value.
        """

        if np.any((value < self.low) | (value > self.high)):
            return -np.inf

        mus = self["mu"]
        sigmas = self["sigma"]
        weights = self["weight"]

        # get current mus and sigmas from values
        for i in range(self.nmodes):
            if not self.fixed["mu"][i]:
                param = "mu{}".format(i)
                try:
                    mus[i] = hyperparameters[param]
                except KeyError:
                    raise KeyError(
                        "Cannot calculate log probability when "
                        "value '{}' is not given".format(param)
                    )

            if not self.fixed["sigma"][i]:
                param = "sigma{}".format(i)
                try:
                    sigmas[i] = hyperparameters[param]
                except KeyError:
                    raise KeyError(
                        "Cannot calculate log probability when "
                        "value '{}' is not given".format(param)
                    )

            if not self.fixed["weight"][i]:
                param = "weight{}".format(i)
                try:
                    weights[i] = hyperparameters[param]
                except KeyError:
                    raise KeyError(
                        "Cannot calculate log probability when "
                        "value '{}' is not given".format(param)
                    )

        if np.any(np.asarray(sigmas) <= 0.0):
            return -np.inf

        if np.any(np.asarray(weights) <= 0.0):
            return -np.inf

        # normalise weights
        lweights = np.log(np.asarray(weights) / np.sum(weights))

        # get log pdf
        if isinstance(value, (float, int)):
            logpdf = -np.inf
        elif isinstance(value, (list, np.ndarray)):
            logpdf = np.full_like(value, -np.inf)
        else:
            raise TypeError("value must be a float or array-like")

        for mu, sigma, lweight in zip(mus, sigmas, lweights):
            lpdf = lweight + truncnorm.logpdf(
                value,
                (self.low - mu) / sigma,
                (self.high - mu) / sigma,
                loc=mu,
                scale=sigma,
            )
            logpdf = np.logaddexp(logpdf, lpdf)

        return logpdf

    def sample(self, hyperparameters={}, size=1):
        """
        Draw a sample from the bounded Gaussian distribution as defined by the
        given hyperparameters.

        Parameters
        ----------
        hyperparameters: dict
            A dictionary of the hyperparameter values that define the current
            state of the distribution.
        size: int
            The number of samples to draw. Default is 1.

        Returns
        -------
        sample:
            A sample, or set of samples, from the distribution.
        """

        mus = self["mu"]
        sigmas = self["sigma"]
        weights = self["weight"]

        # get current mus and sigmas from values
        for i in range(self.nmodes):
            if not self.fixed["mu"][i]:
                param = "mu{}".format(i)
                try:
                    mus[i] = hyperparameters[param]
                except KeyError:
                    raise KeyError(
                        "Cannot calculate log probability when "
                        "value '{}' is not given".format(param)
                    )

            if not self.fixed["sigma"][i]:
                param = "sigma{}".format(i)
                try:
                    sigmas[i] = hyperparameters[param]
                except KeyError:
                    raise KeyError(
                        "Cannot calculate log probability when "
                        "value '{}' is not given".format(param)
                    )

            if not self.fixed["weight"][i]:
                param = "weight{}".format(i)
                try:
                    weights[i] = hyperparameters[param]
                except KeyError:
                    raise KeyError(
                        "Cannot calculate log probability when "
                        "value '{}' is not given".format(param)
                    )

        # cumulative normalised weights
        cweights = np.cumsum(np.asarray(weights) / np.sum(weights))

        # pick mode and draw sample
        if self.nmodes == 1:
            sample = truncnorm.rvs(
                (self.low - mus[0]) / sigmas[0],
                (self.high - mus[0]) / sigmas[0],
                loc=mus[0],
                scale=sigmas[0],
                size=size,
            )
        else:
            sample = np.zeros(size)
            for i in range(size):
                mode = np.argwhere(cweights - np.random.rand() > 0)[0][0]

                sample[i] = truncnorm.rvs(
                    (self.low - mus[mode]) / sigmas[mode],
                    (self.high - mus[mode]) / sigmas[mode],
                    loc=mus[mode],
                    scale=sigmas[mode],
                    size=1,
                )

            if size == 1:
                sample = sample[0]

        return sample


class ExponentialDistribution(BaseDistribution):
    """
    A distribution to define estimating the parameters of an exponential distribution.

    Parameters
    ----------
    name: str
        See :class:`~cwinpy.hierarchical.BaseDistribution`
    mu: array_like
        The mean of the exponential distribution.
    """

    def __init__(self, name, mu):
        # initialise
        super().__init__(
            name, "exponential", hyperparameters=dict(mu=mu), low=0.0, high=np.inf
        )

    def log_pdf(self, value, hyperparameters={}):
        """
        The natural logarithm of the pdf of an exponential distribution.

        Parameters
        ----------
        value: float
            The value at which the probability is to be evaluated.
        hyperparameters: dict
            A dictionary containing the current values of the hyperparameters
            that need to be inferred.

        Returns
        -------
        logpdf:
            The natural logarithm of the probability at the given value.
        """

        if np.any((value < self.low) | (value > self.high)):
            return -np.inf

        mu = self["mu"]
        if not self.fixed["mu"]:
            try:
                mu = hyperparameters["mu"]
            except KeyError:
                raise KeyError("Cannot evaluate the probability when mu is not given")

        if mu <= 0.0:
            return -np.inf

        # get log pdf
        logpdf = expon.logpdf(value, scale=mu)

        return logpdf

    def sample(self, hyperparameters={}, size=1):
        """
        Draw a sample from the exponential distribution as defined by the
        given hyperparameters.

        Parameters
        ----------
        hyperparameters: dict
            A dictionary of the hyperparameter values (``mu``) that define the
            current state of the distribution.
        size: int
            The number of samples to draw from the distribution.

        Returns
        -------
        sample:
            A sample, or set of samples, from the distribution.
        """

        mu = self["mu"]
        if not self.fixed["mu"]:
            try:
                mu = hyperparameters["mu"]
            except KeyError:
                raise KeyError("Cannot evaluate the probability when mu is not given")

        samples = expon.rvs(scale=mu, size=size)

        while 1:
            idx = (samples > self.low) & (samples < self.high)
            nvalid = np.sum(idx)

            if nvalid != size:
                sample = expon.rvs(scale=mu, size=(size - nvalid))
                samples[~idx] = sample
            else:
                break

        if size == 1:
            sample = samples[0]
        else:
            sample = samples

        return sample


class DeltaFunctionDistribution(BaseDistribution):
    """
    A distribution defining a delta function (useful if wanting to fix a
    parameter at a specific value if creating signals, or use as a null model).

    Parameters
    ----------
    name: str
        See :class:`~cwinpy.hierarchical.BaseDistribution`
    peak: float
        The value at which the delta function is non-zero.
    """

    def __init__(self, name, peak):
        # initialise
        super().__init__(
            name, "deltafunction", hyperparameters=dict(peak=peak),
        )

    def log_pdf(self, value, hyperparameters={}):
        """
        The natural logarithm of the pdf of a delta function distribution.

        Parameters
        ----------
        value: float
            The value at which the probability is to be evaluated.
        hyperparameters: dict
            A dictionary containing the current values of the hyperparameters
            that need to be inferred.

        Returns
        -------
        logpdf:
            The natural logarithm of the probability at the given value.
        """

        peak = self["peak"]
        if not self.fixed["peak"]:
            try:
                peak = hyperparameters["peak"]
            except KeyError:
                raise KeyError("Cannot evaluate the probability when peak is not given")

        if value != peak:
            return -np.inf
        return 0.0

    def sample(self, hyperparameters={}, size=1):
        """
        Return the position of the delta function.

        Parameters
        ----------
        hyperparameters: dict
            A dictionary of the hyperparameter values (``peak``) that define
            the current state of the distribution.
        size: int
            The number of samples to draw from the distribution.

        Returns
        -------
        sample:
            A sample, or set of samples, from the distribution.
        """

        peak = self["peak"]
        if not self.fixed["peak"]:
            try:
                peak = hyperparameters["peak"]
            except KeyError:
                raise KeyError("Cannot evaluate the probability when peak is not given")

        if size == 1:
            return peak
        else:
            return peak * np.ones(size)


def create_distribution(name, distribution, distkwargs={}):
    """
    Function to create a distribution.

    Parameters
    ----------
    name: str
        The name of the parameter which the distribution represents.
    distribution: str, :class:`cwinpy.hierarchical.BaseDistribution`
        A string giving a valid distribution name. This is the distribution for
        which the hyperparameters are going to be inferred. If using a string,
        the distribution keyword arguments must be passed using ``distkwargs``.
    distkwargs: dict
        A dictionary of keyword arguments for the distribution that is being
        inferred.

    Returns
    -------
    distribution
        The distribution class.
    """

    if isinstance(distribution, BaseDistribution):
        return distribution
    elif isinstance(distribution, str):
        if distribution.lower() not in DISTRIBUTION_REQUIREMENTS.keys():
            raise ValueError('Unknown distribution type "{}"'.format(distribution))

        if distribution.lower() == "gaussian":
            return BoundedGaussianDistribution(name, **distkwargs)
        elif distribution.lower() == "exponential":
            return ExponentialDistribution(name, **distkwargs)
        elif distribution.lower() == "deltafunction":
            return DeltaFunctionDistribution(name, **distkwargs)
    else:
        raise TypeError("Unknown distribution")


class MassQuadrupoleDistribution(object):
    """
    A class infer the hyperparameters of the :math:`l=m=2` mass quadrupole
    distribution for a given selection of known pulsars (see, for example,
    [1]_).

    The class currently can attempt to fit the hyperparameters for the
    following distributions:

    * a :math:`n`-mode bounded Gaussian distribution defined by either fixed or
      unknown means and standard deviations;
    * an exponential distribution defined by an unknown mean.

    All distributions do not allow the quadrupole value to become negative.

    Parameters
    ----------
    data: :class:`bilby.core.result.ResultList`
        A :class:`bilby.core.result.ResultList` of outputs from running source
        parameter estimation using bilby for a set of individual CW sources.
        These can be from MCMC or nested sampler runs, but only the latter can
        be used if requiring a properly normalised evidence value.
    q22range: array_like
        A list of values at which the :math:`Q_{22}` parameter posteriors
        should be interpolated, or a lower and upper bound in the range of
        values, which will be split into ``q22bins`` points spaced linearly in
        log-space. If not supplied this will instead be set using the posterior
        samples, with a minimum value at zero and a maximum given by the
        maximum of all posterior samples.
    q22bins: int
        The number of bins in :math:`Q_{22}` at which the posterior will be
        interpolated.
    distribution: :class:`cwinpy.hierarchical.BaseDistribution`, str
        A predefined distribution, or string giving a valid distribution name.
        This is the distribution for which the hyperparameters are going to be
        inferred. If using a string, the distribution keyword arguments must be
        passed using ``distkwargs``.
    distkwargs: dict
        A dictionary of keyword arguments for the distribution that is being
        inferred.
    bw: str, scalar, callable
        See the ``bw_method`` argument for :class:`scipy.stats.gaussian_kde`.
    sampler: str
        The name of the stochastic sampler method used by ``bilby`` for
        sampling the posterior. This defaults to use 'dynesty'.
    sampler_kwargs: dict
        A dictionary of arguments required by the given sampler.
    grid: dict
        A dictionary of values that define a grid in the parameter and
        hyperparameter space that can be used by a
        :class:`bilby.core.grid.Grid`. If given sampling will be performed on
        the grid, rather than using the stochastic sampler.
    integration_method: str
        The method to use for integration over the :math:`Q_{22}` parameter for
        each source. Default is 'numerical' to perform trapezium rule
        integration. Other allowed values are: 'sample' to sample over each
        individual :math:`Q_{22}` parameter for each source; or, 'expectation',
        which uses the :math:`Q_{22}` posterior samples to approximate the
        expectation value of the hyperparameter distribution. At the moment,
        these two additional methods may not be correct/reliable.

    To do
    -----

    Distributions that could be added include:

    * a power law distribution with an unknown spectral index, or a (single)
      broken power law with two unknown indices and a known or unknown break
      point;
    * a Student's t-distributions with unknown mean and number of degrees of
      freedom.

    References
    ----------

    .. [1] M. Pitkin, C. Messenger & X. Fan, Phys. Rev. D, 98, 063001, 2018
       (`arXiv:1807.06726 <https://arxiv.org/abs/1807.06726>`_)
    """

    def __init__(
        self,
        data=None,
        q22range=None,
        q22bins=100,
        distribution=None,
        distkwargs=None,
        bw="scott",
        sampler="dynesty",
        sampler_kwargs={},
        grid=None,
        integration_method="numerical",
    ):
        self._posterior_samples = []
        self._posterior_kdes = []
        self._likelihood_kdes_interp = []

        # set the values of q22 at which to calculate the KDE interpolator
        self.set_q22range(q22range, q22bins)

        # set the data
        self.add_data(data, bw=bw)

        # set the sampler
        if grid is None:
            self.set_sampler(sampler, sampler_kwargs)
        else:
            self.set_grid(grid)

        # set integration method
        self.set_integration_method(integration_method)

        # set the distribution
        self.set_distribution(distribution, distkwargs)

    def set_q22range(self, q22range, q22bins=100, prependzero=True):
        """
        Set the values of :math:`Q_{22}`, either directly, or as a set of
        points linear in log-space defined by a lower and upper bounds and
        number of bins, at which to evaluate the posterior samples via their
        KDE to make an interpolator.

        Parameters
        ----------
        q22range: array_like
            If this array contains two values it is assumed that these are the
            lower and upper bounds of a range, and the ``q22bins`` parameter
            sets the number of bins in log-space that the range will be split
            into. Otherwise, if more than two values are given it is assumed
            these are the values for :math:`Q_{22}`.
        q22bins: int
            The number of bins the range is split into.
        prependzero: bool
            If setting an upper and lower range, this will prepend zero at the
            start of the range. Default is True.
        """

        self._q22bins = q22bins

        if q22range is None:
            self._q22_interp_values = None
            return

        if len(q22range) == 2:
            if q22range[1] < q22range[0]:
                raise ValueError("Q22 range is badly defined")
            self._q22_interp_values = np.logspace(
                np.log10(q22range[0]), np.log10(q22range[1]), self._q22bins
            )

            if prependzero:
                self._q22_interp_values = np.insert(self._q22_interp_values, 0, 0)
        elif len(q22range) > 2:
            self._q22_interp_values = q22range
        else:
            raise ValueError("Q22 range is badly defined")

    @property
    def interpolated_log_kdes(self):
        """
        Return the list of interpolation functions for the natural logarithm of
        the :math:`Q_{22}` likelihood functions after a Gaussian KDE has been
        applied.
        """

        return self._likelihood_kdes_interp

    def add_data(self, data, bw="scott"):
        """
        Set the data, i.e., the individual source posterior distributions, on
        which the hierarchical analysis will be performed.

        The posterior samples must include the ``Q22`` :math:`l=m=2` parameter
        for this inference to be performed. The samples will be converted to
        a KDE (reflected about zero to avoid edge effects, and re-normalised),
        using :class:`scipy.stats.gaussian_kde`, which ultimately can be used as
        the data for hierarchical inference. For speed, interpolation functions
        of the natural logarithm of the KDEs, are stored. If the posterior
        samples come with a Bayesian evidence value, and the prior is present,
        then these are used to convert the posterior distribution into a
        likelihood, which is what is then stored in the interpolation function.

        Parameters
        ----------
        data: :class:`bilby.core.result.ResultList`
            A list, or single, results from bilby containing posterior samples
            for a set of sources, or individual source.
        bw: str, scale, callable
            The Gaussian KDE bandwidth calculation method as required by
            :class:`scipy.stats.gaussian_kde`. The default is the 'scott'
            method.
        """

        # check the data is a ResultList
        if not isinstance(data, bilby.core.result.ResultList):
            if isinstance(data, (bilby.core.result.Result, str)):
                # convert to a ResultList
                data = bilby.core.result.ResultList([data])
            elif isinstance(data, list):
                data = bilby.core.result.ResultList(data)
            elif data is None:
                return
            else:
                raise TypeError("Data is not a known type")

        for result in data:
            # check all posteriors contain Q22
            if (
                "Q22" not in result.posterior.columns
                and "q22" not in result.posterior.columns
            ):
                raise RuntimeError("Results do not contain Q22")

        if self._q22_interp_values is None:
            # set q22 range from data
            maxq22 = np.max(
                [
                    res.posterior["q22"].max()
                    if "q22" in res.posterior.columns
                    else res.posterior["Q22"].max()
                    for res in data
                ]
            )
            minq22 = np.min(
                [
                    res.posterior["q22"].min()
                    if "q22" in res.posterior.columns
                    else res.posterior["Q22"].min()
                    for res in data
                ]
            )
            self.set_q22range([minq22, maxq22], self._q22bins)

        # create KDEs
        for result in data:
            self._bw = bw

            try:
                q22str = "q22" if "q22" in result.posterior.columns else "Q22"
                samples = result.posterior[q22str]

                # get reflected samples
                samps = np.concatenate((samples, -samples))

                # calculate KDE
                kde = gaussian_kde(samps, bw_method=bw)
                self._posterior_kdes.append(kde)

                # use log pdf for the kde
                interpvals = kde.logpdf(self._q22_interp_values) + np.log(
                    2.0
                )  # multiply by 2 so pdf normalises to 1
            except Exception as e:
                raise RuntimeError("Problem creating KDE: {}".format(e))

            # convert posterior to likelihood (if possible)
            if np.isfinite(result.log_evidence):
                # multiply by evidence
                interpvals += result.log_evidence

            # divide by Q22 prior
            if q22str not in [key for key in result.priors]:
                raise KeyError("Prior contains no Q22 value")
            prior = result.priors[q22str]
            interpvals -= prior.ln_prob(self._q22_interp_values)

            # create and add interpolator
            self._likelihood_kdes_interp.append(
                interp1d(self._q22_interp_values, interpvals)
            )

            # append samples
            self._posterior_samples.append(samples)

    def set_distribution(self, distribution, distkwargs={}):
        """
        Set the distribution who's hyperparameters are going to be inferred.

        Parameters
        ----------
        distribution: :class:`cwinpy.hierarchical.BaseDistribution`, str
            A predefined distribution, or string giving a valid distribution
            name. If using a string, the distribution keyword arguments must be
            passed using ``distkwargs``.
        distkwargs: dict
            A dictionary of keyword arguments for the distribution that is being
            inferred.
        """

        self._distribution = None
        self._prior = None
        self._likelihood = None

        if distribution is None:
            return

        if isinstance(distribution, BaseDistribution):
            if distribution.name.upper() != "Q22":
                raise ValueError("Distribution name must be 'Q22'")
            else:
                self._distribution = distribution
        elif isinstance(distribution, str):
            self._distribution = create_distribution(
                "Q22", distribution.lower(), distkwargs
            )

        # set the priors from the distribution
        self._set_priors()

        # set the likelihood function
        self._set_likelihood()

    def _set_priors(self):
        """
        Set the priors based on those supplied via the distribution class.
        """

        # get the priors from the distribution
        if len(self._distribution.unknown_parameters) < 1:
            raise ValueError("Distribution has no parameters to infer")

        # add priors as PriorDict
        self._prior = {
            param: prior
            for param, prior in zip(
                self._distribution.unknown_parameters, self._distribution.unknown_priors
            )
        }

    def _set_likelihood(self):
        """
        Set the likelihood.
        """

        samples = None
        q22grid = None
        likelihoods = None

        if self._integration_method == "expectation":
            samples = self._posterior_samples
        elif self._integration_method == "numerical":
            q22grid = self._q22_interp_values
            likelihoods = self._likelihood_kdes_interp
        else:
            likelihoods = self._likelihood_kdes_interp

        self._likelihood = MassQuadrupoleDistributionLikelihood(
            self._distribution,
            likelihoods=likelihoods,
            samples=samples,
            q22grid=q22grid,
        )

    def set_sampler(self, sampler="dynesty", sampler_kwargs={}):
        """
        Set the stochastic sampling method for ``bilby`` to use when sampling
        the parameter and hyperparameter posteriors.

        Parameters
        ----------
        sampler: str
            The name of the stochastic sampler method used by ``bilby`` for
            sampling the posterior. This defaults to use 'dynesty'.
        sampler_kwargs: dict
            A dictionary of arguments required by the given sampler.
        """

        self._sampler = sampler
        if self._sampler not in bilby.core.sampler.IMPLEMENTED_SAMPLERS:
            raise ValueError(
                'Sampler "{}" is not implemented in ' "bilby".format(self._sampler)
            )
        self._sampler_kwargs = sampler_kwargs
        self._use_grid = False  # set to not use the Grid sampling

    def set_grid(self, grid):
        """
        Set a grid on which to evaluate the hyperparameter posterior, as used
        by :class:`bilby.core.grid.Grid`.

        Parameters
        ----------
        grid: dict
            A dictionary of values that define a grid in the hyperparameter
            space that can be used by a :class:`bilby.core.grid.Grid` class.
        """

        if not isinstance(grid, dict):
            raise TypeError("Grid must be a dictionary")

        self._grid = grid
        self._use_grid = True

    def set_integration_method(self, integration_method="numerical"):
        """
        Set the method to use for integration over the :math:`Q_{22}` parameter
        for each source.

        Parameters
        ----------
        integration_method: str
            Default is 'numerical' to perform trapezium rule integration.
            Other allowed values are: 'sample' to sample over each individual
            :math:`Q_{22}` parameter for each source; or, 'expectation', which
            uses the :math:`Q_{22}` posterior samples to approximate the
            expectation value of the hyperparameter distribution. At the
            moment, these two additional methods may not be correct/reliable.
        """

        if not isinstance(integration_method, str):
            raise TypeError("integration method must be a string")

        if integration_method.lower() not in ["numerical", "sample", "expectation"]:
            raise ValueError(
                "Unrecognised integration method type "
                "'{}'".format(integration_method)
            )

        self._integration_method = integration_method.lower()

    @property
    def result(self):
        """
        Return the ``bilby`` object containing the results. If evaluating the
        posterior over a grid this is a :class:`bilby.core.grid.Grid` object.
        If sampling using a stochastic sampler, this is a
        :class:`bilby.core.result.Result` object.
        """

        if self._use_grid:
            return self._grid_result
        else:
            return self._result

    def sample(self, **run_kwargs):
        """
        Sample the posterior distribution using ``bilby``. This can take
        keyword argument required by the bilby `run sampler() <https://lscsoft.docs.ligo.org/bilby/samplers.html#bilby.run_sampler>`_  # noqa: E501
        method.
        """

        # set use_ratio to False by default, i.e., don't use the likelihood
        # ratio
        run_kwargs.setdefault("use_ratio", False)

        if self._use_grid:
            self._grid_result = bilby.core.grid.Grid(
                self._likelihood, self._prior, grid_size=self._grid
            )
        else:
            self._result = bilby.run_sampler(
                likelihood=self._likelihood,
                priors=self._prior,
                sampler=self._sampler,
                **self._sampler_kwargs,
                **run_kwargs
            )

        return self.result


class MassQuadrupoleDistributionLikelihood(bilby.core.likelihood.Likelihood):
    """
    The likelihood function for the inferring the hyperparameters of the
    mass quadrupole, :math:`Q_{22}`, distribution.

    Parameters
    ----------
    distribution: :class:`cwinpy.hierarchical.BaseDistribution`
        The probability distribution for which the hyperparameters are going
        to be inferred.
    likelihoods: list
        A list of interpolation functions each of which gives the likelihood
        function for a single source.
    q22grid: array_like
        If given, the integration over the mass quadrupole distribution for
        each source is performed numerically on at these grid points. If not
        given, individual samples from :math:`Q_{22}` will be drawn from each
        source (i.e., equivalent to having a new :math:`Q_{22}` parameter for
        each source in the sampler).
    samples: list
        A list of arrays of :math:`Q_{22}` samples for each source. If this is
        given then these samples will be used to approximate the integral over
        independent :math:`Q_{22}` variables for each source.
    """

    def __init__(self, distribution, likelihoods=None, q22grid=None, samples=None):
        if not isinstance(distribution, BaseDistribution):
            raise TypeError("Distribution is not the correct type")

        # check that the distribution contains parameters to be inferred
        if len(distribution.unknown_parameters) < 1:
            raise ValueError("Distribution has no parameters to infer")

        inferred_parameters = {param: None for param in distribution.unknown_parameters}
        self.distribution = distribution
        self.q22grid = q22grid
        self.likelihoods = likelihoods
        self.samples = samples

        super().__init__(parameters=inferred_parameters)

    @property
    def likelihoods(self):
        return self._likelihoods

    @likelihoods.setter
    def likelihoods(self, like):
        if like is None:
            self._likelihoods = None
            self._nsources = 0
        elif not isinstance(like, list):
            raise TypeError("Likelihoods must be a list")
        else:
            if self.q22grid is not None:
                # evaluate the interpolated (log) likelihoods on the grid
                self._likelihoods = []
                for ll in like:
                    self._likelihoods.append(ll(self.q22grid))
                self._nsources = len(like)
            else:
                raise ValueError("Q22 grid must be set to evaluate likelihoods")

    @property
    def q22grid(self):
        return self._q22grid

    @q22grid.setter
    def q22grid(self, q22grid):
        if isinstance(q22grid, (list, np.ndarray)):
            self._q22grid = np.asarray(q22grid)
        elif q22grid is None:
            self._q22grid = None
        else:
            raise TypeError("Q22 grid must be array-like")

    @property
    def samples(self):
        return self._samples

    @samples.setter
    def samples(self, samples):
        if samples is not None:
            if not isinstance(samples, (list, np.ndarray)):
                raise TypeError("samples value must be a list")

            if isinstance(samples, np.ndarray):
                if len(samples.shape) != 2:
                    raise ValueError("Samples must be a 2D array")

            for samplelist in samples:
                if not isinstance(samplelist, (list, np.ndarray)):
                    raise TypeError("Samples must be a list")

                if len(np.asarray(samplelist).shape) != 1:
                    raise ValueError("Source samples must be a 1d list")

            self._nsources = len(samples)

        self._samples = samples

    def log_likelihood(self):
        """
        Evaluate the log likelihood.
        """

        log_like = 0.0  # initialise the log likelihood

        if self.samples is not None:
            # log-likelihood using expectation value from samples
            for samps in self.samples:
                log_like += np.log(
                    np.mean(self.distribution.pdf(samps, self.parameters, samps))
                )
        else:
            # evaluate the hyperparameter distribution
            logp = self.distribution.log_pdf(self.q22grid, self.parameters)

            # log-likelihood numerically integrating over Q22
            for logl in self.likelihoods:
                log_like += logtrapz(logp + logl, self.q22grid)

        return log_like

    def noise_log_likelihood(self):
        """
        The log-likelihood for the unknown hyperparameters being equal to
        with zero.

        Note
        ----

        For distributions with hyperparameter priors that exclude zero this
        will always given :math:`-\\infty`.
        """

        for p in self.parameters:
            self.parameters[p] = 0.0

        return self.log_likelihood()

    def __len__(self):
        return self._nsources
