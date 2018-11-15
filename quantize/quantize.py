"""
====================================================================
K-means clustering and vector quantization (:mod:`scipy.cluster.vq`)
====================================================================

Provides routines for k-means clustering, generating code books
from k-means models, and quantizing vectors by comparing them with
centroids in a code book.

.. autosummary::
   :toctree: generated/

   whiten -- Normalize a group of observations so each feature has unit variance
   vq -- Calculate code book membership of a set of observation vectors
   kmeans -- Performs k-means on a set of observation vectors forming k clusters
   kmeans2 -- A different implementation of k-means with more methods
           -- for initializing centroids

Background information
======================
The k-means algorithm takes as input the number of clusters to
generate, k, and a set of observation vectors to cluster.  It
returns a set of centroids, one for each of the k clusters.  An
observation vector is classified with the cluster number or
centroid index of the centroid closest to it.

A vector v belongs to cluster i if it is closer to centroid i than
any other centroids. If v belongs to i, we say centroid i is the
dominating centroid of v. The k-means algorithm tries to
minimize distortion, which is defined as the sum of the squared distances
between each observation vector and its dominating centroid.  Each
step of the k-means algorithm refines the choices of centroids to
reduce distortion. The change in distortion is used as a
stopping criterion: when the change is lower than a threshold, the
k-means algorithm is not making sufficient progress and
terminates. One can also define a maximum number of iterations.

Since vector quantization is a natural application for k-means,
information theory terminology is often used.  The centroid index
or cluster index is also referred to as a "code" and the table
mapping codes to centroids and vice versa is often referred as a
"code book". The result of k-means, a set of centroids, can be
used to quantize vectors. Quantization aims to find an encoding of
vectors that reduces the expected distortion.

All routines expect obs to be a M by N array where the rows are
the observation vectors. The codebook is a k by N array where the
i'th row is the centroid of code word i. The observation vectors
and centroids have the same feature dimension.

As an example, suppose we wish to compress a 24-bit color image
(each pixel is represented by one byte for red, one for blue, and
one for green) before sending it over the web.  By using a smaller
8-bit encoding, we can reduce the amount of data by two
thirds. Ideally, the colors for each of the 256 possible 8-bit
encoding values should be chosen to minimize distortion of the
color. Running k-means with k=256 generates a code book of 256
codes, which fills up all possible 8-bit sequences.  Instead of
sending a 3-byte value for each pixel, the 8-bit centroid index
(or code word) of the dominating centroid is transmitted. The code
book is also sent over the wire so each 8-bit code can be
translated back to a 24-bit pixel value representation. If the
image of interest was of an ocean, we would expect many 24-bit
blues to be represented by 8-bit codes. If it was an image of a
human face, more flesh tone colors would be represented in the
code book.

"""
from __future__ import division, print_function, absolute_import

__docformat__ = 'restructuredtext'

__all__ = ['whiten', 'vq', 'kmeans', 'kmeans2']

# TODO:
#   - implements high level method for running several times k-means with
#   different initialization
#   - warning: what happens if different number of clusters ? For now, emit a
#   warning, but it is not great, because I am not sure it really make sense to
#   succeed in this case (maybe an exception is better ?)

import warnings

import numpy as np
from scipy._lib._util import _asarray_validated
from scipy._lib import _numpy_compat

from . import _quantize


class ClusterError(Exception):
    pass


def whiten(obs, check_finite=True):
    """
    Normalize a group of observations on a per feature basis.

    Before running k-means, it is beneficial to rescale each feature
    dimension of the observation set with whitening. Each feature is
    divided by its standard deviation across all observations to give
    it unit variance.

    Parameters
    ----------
    obs : ndarray
        Each row of the array is an observation.  The
        columns are the features seen during each observation.

        >>> #         f0    f1    f2
        >>> obs = [[  1.,   1.,   1.],  #o0
        ...        [  2.,   2.,   2.],  #o1
        ...        [  3.,   3.,   3.],  #o2
        ...        [  4.,   4.,   4.]]  #o3

    check_finite : bool, optional
        Whether to check that the input matrices contain only finite numbers.
        Disabling may give a performance gain, but may result in problems
        (crashes, non-termination) if the inputs do contain infinities or NaNs.
        Default: True

    Returns
    -------
    result : ndarray
        Contains the values in `obs` scaled by the standard deviation
        of each column.

    Examples
    --------
    >>> from scipy.cluster.vq import whiten
    >>> features  = np.array([[1.9, 2.3, 1.7],
    ...                       [1.5, 2.5, 2.2],
    ...                       [0.8, 0.6, 1.7,]])
    >>> whiten(features)
    array([[ 4.17944278,  2.69811351,  7.21248917],
           [ 3.29956009,  2.93273208,  9.33380951],
           [ 1.75976538,  0.7038557 ,  7.21248917]])

    """
    obs = _asarray_validated(obs, check_finite=check_finite)
    std_dev = np.std(obs, axis=0)
    zero_std_mask = std_dev == 0
    if zero_std_mask.any():
        std_dev[zero_std_mask] = 1.0
        warnings.warn("Some columns have standard deviation zero. "
                      "The values of these columns will not change.",
                      RuntimeWarning)
    return obs / std_dev


def vq(obs, code_book, check_finite=True, matrix=None):
    """
    Assign codes from a code book to observations.

    Assigns a code from a code book to each observation. Each
    observation vector in the 'M' by 'N' `obs` array is compared with the
    centroids in the code book and assigned the code of the closest
    centroid.

    The features in `obs` should have unit variance, which can be
    achieved by passing them through the whiten function.  The code
    book can be created with the k-means algorithm or a different
    encoding algorithm.

    Parameters
    ----------
    obs : ndarray
        Each row of the 'M' x 'N' array is an observation.  The columns are
        the "features" seen during each observation. The features must be
        whitened first using the whiten function or something equivalent.
    code_book : ndarray
        The code book is usually generated using the k-means algorithm.
        Each row of the array holds a different code, and the columns are
        the features of the code.

         >>> #              f0    f1    f2   f3
         >>> code_book = [
         ...             [  1.,   2.,   3.,   4.],  #c0
         ...             [  1.,   2.,   3.,   4.],  #c1
         ...             [  1.,   2.,   3.,   4.]]  #c2

    check_finite : bool, optional
        Whether to check that the input matrices contain only finite numbers.
        Disabling may give a performance gain, but may result in problems
        (crashes, non-termination) if the inputs do contain infinities or NaNs.
        Default: True

    Returns
    -------
    code : ndarray
        A length M array holding the code book index for each observation.
    dist : ndarray
        The distortion (distance) between the observation and its nearest
        code.

    Examples
    --------
    >>> from numpy import array
    >>> from scipy.cluster.vq import vq
    >>> code_book = array([[1.,1.,1.],
    ...                    [2.,2.,2.]])
    >>> features  = array([[  1.9,2.3,1.7],
    ...                    [  1.5,2.5,2.2],
    ...                    [  0.8,0.6,1.7]])
    >>> vq(features,code_book)
    (array([1, 1, 0],'i'), array([ 0.43588989,  0.73484692,  0.83066239]))

    """
    obs = _asarray_validated(obs, check_finite=check_finite)
    code_book = _asarray_validated(code_book, check_finite=check_finite)
    ct = np.common_type(obs, code_book)

    c_obs = obs.astype(ct, copy=False)

    if code_book.dtype != ct:
        c_code_book = code_book.astype(ct)
    else:
        c_code_book = code_book
    if matrix is not None:
        results = py_vq_mahalanobis(c_obs, c_code_book, matrix=matrix)
    elif ct in (np.float32, np.float64):
        results = _quantize.vq(c_obs, c_code_book)
    else:
        results = py_vq(obs, code_book)
    return results


def py_vq_mahalanobis(obs, code_book, check_finite=True, matrix=None):
    """ Python version of vq algorithm.

    The algorithm computes the euclidian distance between each
    observation and every frame in the code_book.

    Parameters
    ----------
    obs : ndarray
        Expects a rank 2 array. Each row is one observation.
    code_book : ndarray
        Code book to use. Same format than obs. Should have same number of
        features (eg columns) than obs.
    check_finite : bool, optional
        Whether to check that the input matrices contain only finite numbers.
        Disabling may give a performance gain, but may result in problems
        (crashes, non-termination) if the inputs do contain infinities or NaNs.
        Default: True

    Returns
    -------
    code : ndarray
        code[i] gives the label of the ith obversation, that its code is
        code_book[code[i]].
    mind_dist : ndarray
        min_dist[i] gives the distance between the ith observation and its
        corresponding code.

    Notes
    -----
    This function is slower than the C version but works for
    all input types.  If the inputs have the wrong types for the
    C versions of the function, this one is called as a last resort.

    It is about 20 times slower than the C version.

    """
    obs = _asarray_validated(obs, check_finite=check_finite)
    code_book = _asarray_validated(code_book, check_finite=check_finite)

    # n = number of observations
    # d = number of features
    if np.ndim(obs) == 1:
        if not np.ndim(obs) == np.ndim(code_book):
            raise ValueError(
                    "Observation and code_book should have the same rank")
        else:
            return _py_vq_1d(obs, code_book)
    else:
        (n, d) = np.shape(obs)

    # code books and observations should have same number of features and same
    # shape
    if not np.ndim(obs) == np.ndim(code_book):
        raise ValueError("Observation and code_book should have the same rank")
    elif not d == code_book.shape[1]:
        raise ValueError("Code book(%d) and obs(%d) should have the same "
                         "number of features (eg columns)""" %
                         (code_book.shape[1], d))

    code = np.zeros(n, dtype=int)
    min_dist = np.zeros(n)
    for i in range(n):
        diff = (obs[i] - code_book)
        dist = np.einsum('ij,ji->i', np.dot(diff, matrix), np.transpose(diff))
        code[i] = np.argmin(dist)
        min_dist[i] = dist[code[i]]

    return code, np.sqrt(min_dist)


def py_vq(obs, code_book, check_finite=True):
    """ Python version of vq algorithm.

    The algorithm computes the euclidian distance between each
    observation and every frame in the code_book.

    Parameters
    ----------
    obs : ndarray
        Expects a rank 2 array. Each row is one observation.
    code_book : ndarray
        Code book to use. Same format than obs. Should have same number of
        features (eg columns) than obs.
    check_finite : bool, optional
        Whether to check that the input matrices contain only finite numbers.
        Disabling may give a performance gain, but may result in problems
        (crashes, non-termination) if the inputs do contain infinities or NaNs.
        Default: True

    Returns
    -------
    code : ndarray
        code[i] gives the label of the ith obversation, that its code is
        code_book[code[i]].
    mind_dist : ndarray
        min_dist[i] gives the distance between the ith observation and its
        corresponding code.

    Notes
    -----
    This function is slower than the C version but works for
    all input types.  If the inputs have the wrong types for the
    C versions of the function, this one is called as a last resort.

    It is about 20 times slower than the C version.

    """
    obs = _asarray_validated(obs, check_finite=check_finite)
    code_book = _asarray_validated(code_book, check_finite=check_finite)

    # n = number of observations
    # d = number of features
    if np.ndim(obs) == 1:
        if not np.ndim(obs) == np.ndim(code_book):
            raise ValueError(
                    "Observation and code_book should have the same rank")
        else:
            return _py_vq_1d(obs, code_book)
    else:
        (n, d) = np.shape(obs)

    # code books and observations should have same number of features and same
    # shape
    if not np.ndim(obs) == np.ndim(code_book):
        raise ValueError("Observation and code_book should have the same rank")
    elif not d == code_book.shape[1]:
        raise ValueError("Code book(%d) and obs(%d) should have the same "
                         "number of features (eg columns)""" %
                         (code_book.shape[1], d))

    code = np.zeros(n, dtype=int)
    min_dist = np.zeros(n)
    for i in range(n):
        dist = np.sum((obs[i] - code_book) ** 2, 1)
        code[i] = np.argmin(dist)
        min_dist[i] = dist[code[i]]

    return code, np.sqrt(min_dist)


def _py_vq_1d(obs, code_book):
    """ Python version of vq algorithm for rank 1 only.

    Parameters
    ----------
    obs : ndarray
        Expects a rank 1 array. Each item is one observation.
    code_book : ndarray
        Code book to use. Same format than obs. Should rank 1 too.

    Returns
    -------
    code : ndarray
        code[i] gives the label of the ith obversation, that its code is
        code_book[code[i]].
    mind_dist : ndarray
        min_dist[i] gives the distance between the ith observation and its
        corresponding code.

    """
    raise RuntimeError("_py_vq_1d buggy, do not use rank 1 arrays for now")
    n = obs.size
    nc = code_book.size
    dist = np.zeros((n, nc))
    for i in range(nc):
        dist[:, i] = np.sum(obs - code_book[i])
    print(dist)
    code = np.argmin(dist)
    min_dist = dist[code]

    return code, np.sqrt(min_dist)


def py_vq2(obs, code_book, check_finite=True):
    """2nd Python version of vq algorithm.

    The algorithm simply computes the euclidian distance between each
    observation and every frame in the code_book/

    Parameters
    ----------
    obs : ndarray
        Expect a rank 2 array. Each row is one observation.
    code_book : ndarray
        Code book to use. Same format than obs. Should have same number of
        features (eg columns) than obs.
    check_finite : bool, optional
        Whether to check that the input matrices contain only finite numbers.
        Disabling may give a performance gain, but may result in problems
        (crashes, non-termination) if the inputs do contain infinities or NaNs.
        Default: True

    Returns
    -------
    code : ndarray
        code[i] gives the label of the ith obversation, that its code is
        code_book[code[i]].
    mind_dist : ndarray
        min_dist[i] gives the distance between the ith observation and its
        corresponding code.

    Notes
    -----
    This could be faster when number of codebooks is small, but it
    becomes a real memory hog when codebook is large. It requires
    N by M by O storage where N=number of obs, M = number of
    features, and O = number of codes.

    """
    obs = _asarray_validated(obs, check_finite=check_finite)
    code_book = _asarray_validated(code_book, check_finite=check_finite)
    d = np.shape(obs)[1]

    # code books and observations should have same number of features
    if not d == code_book.shape[1]:
        raise ValueError("""
            code book(%d) and obs(%d) should have the same
            number of features (eg columns)""" % (code_book.shape[1], d))

    diff = obs[np.newaxis, :, :] - code_book[:,np.newaxis,:]
    dist = np.sqrt(np.sum(diff * diff, -1))
    code = np.argmin(dist, 0)
    min_dist = np.minimum.reduce(dist, 0)
    # The next line I think is equivalent and should be faster than the one
    # above, but in practice didn't seem to make much difference:
    # min_dist = choose(code,dist)
    return code, min_dist


def _kpoints(data, k):
    """Pick k points at random in data (one row = one observation).

    This is done by taking the k first values of a random permutation of 1..N
    where N is the number of observation.

    Parameters
    ----------
    data : ndarray
        Expect a rank 1 or 2 array. Rank 1 are assumed to describe one
        dimensional data, rank 2 multidimensional data, in which case one
        row is one observation.
    k : int
        Number of samples to generate.

    """
    if data.ndim > 1:
        n = data.shape[0]
    else:
        n = data.size

    p = np.random.permutation(n)
    x = data[p[:k], :].copy()

    return x


def _krandinit(data, k):
    """Returns k samples of a random variable which parameters depend on data.

    More precisely, it returns k observations sampled from a Gaussian random
    variable which mean and covariances are the one estimated from data.

    Parameters
    ----------
    data : ndarray
        Expect a rank 1 or 2 array. Rank 1 are assumed to describe one
        dimensional data, rank 2 multidimensional data, in which case one
        row is one observation.
    k : int
        Number of samples to generate.

    """
    def init_rank1(data):
        mu = np.mean(data)
        cov = np.cov(data)
        x = np.random.randn(k)
        x *= np.sqrt(cov)
        x += mu
        return x

    def init_rankn(data):
        mu = np.mean(data, 0)
        cov = np.atleast_2d(np.cov(data, rowvar=0))

        # k rows, d cols (one row = one obs)
        # Generate k sample of a random variable ~ Gaussian(mu, cov)
        x = np.random.randn(k, mu.size)
        x = np.dot(x, np.linalg.cholesky(cov).T) + mu
        return x

    def init_rank_def(data):
        # initialize when the covariance matrix is rank deficient
        mu = np.mean(data, axis=0)
        _, s, vh = np.linalg.svd(data - mu, full_matrices=False)
        x = np.random.randn(k, s.size)
        sVh = s[:, None] * vh / np.sqrt(data.shape[0] - 1)
        x = np.dot(x, sVh) + mu
        return x

    nd = np.ndim(data)
    if nd == 1:
        return init_rank1(data)
    elif data.shape[1] > data.shape[0]:
        return init_rank_def(data)
    else:
        return init_rankn(data)


_valid_init_meth = {'random': _krandinit, 'points': _kpoints}


def _missing_warn():
    """Print a warning when called."""
    warnings.warn("One of the clusters is empty. "
                 "Re-run kmean with a different initialization.")


def _missing_raise():
    """raise a ClusterError when called."""
    raise ClusterError("One of the clusters is empty. "
                        "Re-run kmean with a different initialization.")


_valid_miss_meth = {'warn': _missing_warn, 'raise': _missing_raise}


def kmeans2(data, k, iter=10, thresh=1e-5, minit='random',
        missing='warn', check_finite=True, matrix=None, verbose=True):
    """
    Classify a set of observations into k clusters using the k-means algorithm.

    The algorithm attempts to minimize the Euclidian distance between
    observations and centroids. Several initialization methods are
    included.

    Parameters
    ----------
    data : ndarray
        A 'M' by 'N' array of 'M' observations in 'N' dimensions or a length
        'M' array of 'M' one-dimensional observations.
    k : int or ndarray
        The number of clusters to form as well as the number of
        centroids to generate. If `minit` initialization string is
        'matrix', or if a ndarray is given instead, it is
        interpreted as initial cluster to use instead.
    iter : int, optional
        Number of iterations of the k-means algrithm to run. Note
        that this differs in meaning from the iters parameter to
        the kmeans function.
    thresh : float, optional
        (not used yet)
    minit : str, optional
        Method for initialization. Available methods are 'random',
        'points', and 'matrix':

        'random': generate k centroids from a Gaussian with mean and
        variance estimated from the data.

        'points': choose k observations (rows) at random from data for
        the initial centroids.

        'matrix': interpret the k parameter as a k by M (or length k
        array for one-dimensional data) array of initial centroids.
    missing : str, optional
        Method to deal with empty clusters. Available methods are
        'warn' and 'raise':

        'warn': give a warning and continue.

        'raise': raise an ClusterError and terminate the algorithm.
    check_finite : bool, optional
        Whether to check that the input matrices contain only finite numbers.
        Disabling may give a performance gain, but may result in problems
        (crashes, non-termination) if the inputs do contain infinities or NaNs.
        Default: True

    Returns
    -------
    centroid : ndarray
        A 'k' by 'N' array of centroids found at the last iteration of
        k-means.
    label : ndarray
        label[i] is the code or index of the centroid the
        i'th observation is closest to.

    """
    data = _asarray_validated(data, check_finite=check_finite)
    if missing not in _valid_miss_meth:
        raise ValueError("Unkown missing method: %s" % str(missing))
    # If data is rank 1, then we have 1 dimension problem.
    nd = np.ndim(data)
    if nd == 1:
        d = 1
        # raise ValueError("Input of rank 1 not supported yet")
    elif nd == 2:
        d = data.shape[1]
    else:
        raise ValueError("Input of rank > 2 not supported")

    if np.size(data) < 1:
        raise ValueError("Input has 0 items.")

    # If k is not a single value, then it should be compatible with data's
    # shape
    if np.size(k) > 1 or minit == 'matrix':
        if not nd == np.ndim(k):
            raise ValueError("k is not an int and has not same rank than data")
        if d == 1:
            nc = len(k)
        else:
            (nc, dc) = k.shape
            if not dc == d:
                raise ValueError("k is not an int and has not same rank than\
                        data")
        clusters = k.copy()
    else:
        try:
            nc = int(k)
        except TypeError:
            raise ValueError("k (%s) could not be converted to an integer " % str(k))

        if nc < 1:
            raise ValueError("kmeans2 for 0 clusters ? (k was %s)" % str(k))

        if not nc == k:
            warnings.warn("k was not an integer, was converted.")
        try:
            init = _valid_init_meth[minit]
        except KeyError:
            raise ValueError("unknown init method %s" % str(minit))
        clusters = init(data, k)

    if int(iter) < 1:
        raise ValueError("iter = %s is not valid.  iter must be a positive integer." % iter)
    # clusters[0][:] = 0
    return _kmeans2(data, clusters, iter, nc, _valid_miss_meth[missing], matrix=matrix, verbose=verbose)


def _kmeans2(data, code, niter, nc, missing, matrix=None, verbose=True):
    """ "raw" version of kmeans2. Do not use directly.

    Run k-means with a given initial codebook.

    """
    from tqdm import tqdm
    iterator = tqdm if verbose else lambda x:x
    print(iterator)
    for _ in iterator(range(niter)):
        # normalize
        # norms = np.linalg.norm(code, axis=1)
        # code = code / norms[:, np.newaxis]
        # Compute the nearest neighbour for each obs
        # using the current code book
        label = vq(data, code, matrix=matrix)[0]
        # Update the code by computing centroids using the new code book
        new_code, has_members = _quantize.update_cluster_means(data, label, nc)
        if not has_members.all():
            missing()
            # Set the empty clusters to their previous positions
            new_code[~has_members] = code[~has_members]
        code = new_code

    return code, label
