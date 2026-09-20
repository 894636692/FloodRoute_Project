"""Chinese figures from held-out results, with scenario-seed replication."""
from pathlib import Path
import sys
import hashlib
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from floodroute.runtime import write_json

LABELS = {'shortest':'最短路径', 'risk':'风险优先', 'risk_uncertainty':'风险+不确定性', 'trusted':'可信优先'}
COLORS = ['#222222','#0072B2','#9B5500','#864A8A']
MARKERS = ['o','s','^','D']
POLICIES = {'never':'不重规划', 'always':'每次重规划', 'triggered':'触发式重规划'}


def plot_all(folder):
    frame = pd.read_csv(folder/'test_routes.csv')
    out = folder/'figures'; out.mkdir(exist_ok=True)
    families = {f.name for f in font_manager.fontManager.ttflist}
    font = next((f for f in ['Microsoft YaHei','SimHei','Noto Sans CJK SC'] if f in families), None)
    if font is None: raise RuntimeError('Install a Chinese font before rendering figures')
    plt.rcParams.update({'font.family':font, 'font.size':10, 'axes.unicode_minus':False,
                         'savefig.facecolor':'white', 'figure.facecolor':'white'})
    used = frame[frame.ablation.eq('source_specific')]
    for x, xlabel, filename in [('delay_min','观测延迟（分钟）','观测延迟与风险暴露'),
                                 ('missing_rate','数据缺失率','数据缺失率与风险暴露')]:
        seed_means = used.groupby(['mode','seed',x]).truth_exposure.mean().reset_index()
        seed_means.to_csv(out/f'{filename}_绘图数据.csv', index=False)
        fig, ax = plt.subplots(figsize=(8,4.8), layout='constrained')
        for (mode,label), color, marker in zip(LABELS.items(), COLORS, MARKERS):
            sample = seed_means[seed_means['mode'].eq(mode)]
            summary = sample.groupby(x).truth_exposure.agg(['mean','std'])
            ax.errorbar(summary.index, summary['mean'], yerr=summary['std'], label=label,
                        color=color, marker=marker, capsize=3, linewidth=1.5)
        ax.set(xlabel=xlabel, ylabel='长度加权风险暴露', ylim=(0,1), title=filename)
        ax.grid(alpha=.2); ax.legend(fontsize=9, loc='lower right')
        fig.supxlabel('留出测试：3 个情景种子；点为种子均值，误差线为种子间标准差。\n每个种子内对起终点、决策时刻及其余扰动条件等权平均。', fontsize=9)
        fig.savefig(out/f'{filename}.png', dpi=220); plt.close(fig)

    subset = frame[frame['mode'].eq('trusted')]
    seed_means = subset.groupby(['seed','ablation']).truth_exposure.mean().unstack()
    order = ['no_freshness','universal','source_specific']
    fig, ax = plt.subplots(figsize=(8,4.8), layout='constrained')
    for i, key in enumerate(order):
        ax.errorbar(i, seed_means[key].mean(), yerr=seed_means[key].std(), color='#0072B2', marker='s', capsize=5)
        ax.scatter([i-.08,i,i+.08], seed_means[key], marker='x', color='#555555', s=25)
    ax.set(xticks=range(3), xticklabels=['无时效性惩罚','统一时间尺度','分数据源时间尺度'],
           ylabel='长度加权风险暴露', ylim=(0,1), title='信息时效参数消融')
    ax.grid(axis='y',alpha=.2)
    fig.supxlabel('方点：种子均值；误差线：种子间标准差；叉号：3 个种子各自的平均结果。\n当前仅降雨源启用；所选降雨时间尺度为 60 分钟，与统一尺度相同。',fontsize=9)
    fig.savefig(out/'信息时效参数消融.png',dpi=220);plt.close(fig)
    seed_means.to_csv(out/'信息时效参数消融_绘图数据.csv')

    # Show all held-out seeds; no cherry-picking a successful replay.
    fig, axes = plt.subplots(2,2,figsize=(11,7.5),layout='constrained',sharex=True)
    seeds = sorted(frame.seed.unique())
    plot_rows = []
    for row, (name,title) in enumerate([('T1','突发风险上升场景'),('T2','小幅风险波动场景')]):
        for seed in seeds:
            table = pd.read_csv(folder/f'{name}_{seed}_replay.csv')
            table['benchmark'] = name;table['seed'] = seed;plot_rows.append(table)
            for i,(policy,label) in enumerate(POLICIES.items()):
                sub = table[table.policy.eq(policy)].reset_index(drop=True)
                x = np.arange(len(sub))*15
                axes[row,0].plot(x,sub.truth_exposure,color=COLORS[i],linestyle=['--',':','-'][i],
                                  label=label if seed==seeds[0] else None, alpha=.8)
                axes[row,1].step(x,sub.replan_count,where='post',color=COLORS[i],linestyle=['--',':','-'][i],
                                  label=label if seed==seeds[0] else None,alpha=.8)
                if policy=='triggered':
                    mask = sub.route_changed
                    axes[row,0].scatter(x[mask],sub.loc[mask,'truth_exposure'],marker='D',color=COLORS[i],s=28)
        axes[row,0].set(title=title, ylabel='长度加权风险暴露', ylim=(0,1))
        axes[row,1].set(title='累计重新规划次数',ylabel='次数',ylim=(-.2,12))
        for ax in axes[row]:ax.grid(alpha=.2);ax.legend(fontsize=8);ax.set_xlabel('场景开始后的时间（分钟）')
    fig.suptitle('触发式重规划时间线')
    fig.supxlabel('每种策略绘出全部 3 个留出种子（部分重叠）；菱形标出真正换路。初始规划不计入重新规划次数。',fontsize=9)
    fig.savefig(out/'触发式重规划时间线.png',dpi=220);plt.close(fig)
    pd.concat(plot_rows).to_csv(out/'触发式重规划时间线_绘图数据.csv',index=False)
    write_json(out/'figure_manifest.json', {
        'medium':'student research report, no journal-specific compliance claim',
        'font':font, 'dpi':220, 'replication':'3 scenario seeds; within-seed paired repeated conditions averaged',
        'uncertainty':'sample SD across seed means; not a confidence interval',
        'source_sha256':hashlib.sha256((folder/'test_routes.csv').read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
        'hash_format':'UTF-8 with LF line endings',
        'files':[p.name for p in sorted(out.glob('*.png'))],
        'alt_text':{
            '观测延迟与风险暴露':'比较四种方法在不同观测延迟下的种子平均风险暴露。',
            '数据缺失率与风险暴露':'比较四种方法在不同数据缺失率下的种子平均风险暴露。',
            '信息时效参数消融':'可信优先的三种时效性设置；统一尺度与所选单一降雨源尺度相同。',
            '触发式重规划时间线':'风险上升和小幅波动两种场景中，比较风险暴露及重新规划次数。'}})

if __name__ == '__main__': plot_all(ROOT/'results/experiment_v2')
