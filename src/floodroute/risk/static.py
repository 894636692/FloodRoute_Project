"""A feature susceptibility with explicit missing priors and coverage uncertainty."""
import numpy as np


def static_components(edges, config):
    c=config['static']; prior=c['missing_prior']
    score=np.zeros(len(edges)); unknown=np.zeros(len(edges)); total=0.
    for field, group in [('low_elev_norm','dem'),('flatness_risk','slope'),
                         ('builtup_frac','worldcover'),('water_frac','worldcover'),('vegetation_relief','worldcover')]:
        values=(1-edges.vegetation_frac if field=='vegetation_relief' else edges[field]).to_numpy(float)
        fractions=edges[f'{group}_valid_frac'].to_numpy(float)
        flagged=edges.quality_flag.fillna('unknown').str.split(';').map(lambda ts:f'{group}_insufficient_coverage' in ts).to_numpy()
        valid=np.isfinite(values)&np.isfinite(fractions)&(fractions>=.9)&~flagged
        weight=c[field]; total+=weight
        score+=weight*np.where(valid,np.clip(values,0,1),prior)
        unknown+=weight*np.where(valid,1-np.clip(fractions,0,1),1.)
    return score/total, unknown/total
