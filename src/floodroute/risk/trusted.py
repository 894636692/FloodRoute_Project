"""Explainable v1 index. No ground-truth field or evaluation input is accepted."""
import numpy as np
import pandas as pd
from .static import static_components
from .freshness import freshness


class RiskEngine:
    def __init__(self, edges, config):
        self.config=config
        self.index=pd.MultiIndex.from_frame(edges[['u','v','key']])
        self.static, self.static_unknown=static_components(edges,config)

    def compute(self, observed_sources):
        cfg=self.config; c=cfg['uncertainty']
        risk=self.static*cfg['static']['weight']; denominator=cfg['static']['weight']
        uncertainty=c['base']+c['static_missing']*self.static_unknown
        fresh=[]; source_uncertainty=[]
        output=pd.DataFrame({'static_risk':self.static,'static_missing_fraction':self.static_unknown}, index=self.index)
        for name, settings in cfg['sources'].items():
            if not settings['active']: continue
            frame=observed_sources.get(name,pd.DataFrame()).reindex(self.index)
            def column(key, default):
                return frame[key].to_numpy(float) if key in frame else np.full(len(self.index),default)
            values=column('value',np.nan); coverage=np.nan_to_num(column('coverage',0),nan=0).clip(0,1)
            coverage=np.where(np.isfinite(values),coverage,0)
            age=column('age_min',np.nan)
            f=freshness(age,settings['tau_min'])*coverage
            # Unknown dynamic portion uses declared prior; never silently imputed as dry.
            value=np.nan_to_num(values/settings['scale'],nan=0).clip(0,1)*coverage+(1-coverage)*cfg['static']['missing_prior']
            risk+=settings['weight']*value; denominator+=settings['weight']
            source_uncertainty.append(c['missing']*(1-coverage)+c['quality']*np.nan_to_num(column('quality',1),nan=1))
            fresh.append(f)
            output[f'{name}_freshness']=f; output[f'{name}_age_min']=age
            output[f'{name}_coverage']=coverage
        risk=(risk/denominator).clip(0,1)
        if source_uncertainty: uncertainty+=np.mean(source_uncertainty,axis=0)
        uncertainty=uncertainty.clip(0,1)
        mean_fresh=np.mean(fresh,axis=0) if fresh else np.ones(len(risk))
        output['risk']=risk; output['uncertainty']=uncertainty; output['freshness']=mean_fresh
        output['confidence']=mean_fresh*(1-uncertainty)
        output['risk_uncertainty']=(risk+cfg['trusted']['uncertainty_weight']*uncertainty).clip(0,1)
        output['trusted_risk']=(output.risk_uncertainty+cfg['trusted']['staleness_weight']*(1-mean_fresh)).clip(0,1)
        return output
