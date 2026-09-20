"""Separate source freshness; age is minutes since observation, not file download."""
import numpy as np


def freshness(age_min, tau_min):
    if tau_min <= 0:
        raise ValueError('tau must be positive')
    age=np.asarray(age_min,dtype=float)
    return np.where(np.isfinite(age)&(age>=0),np.exp(-np.maximum(age,0)/tau_min),0.)
