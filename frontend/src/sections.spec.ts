import {describe,expect,it} from 'vitest'
import {activeFlowSegment,activeSectionTab,backtestTabs,dataTabs,paperTabs,trainingTabs} from './sections'

describe('顶栏五段流高亮',()=>{
  it('maps every research path to its segment',()=>{
    expect(activeFlowSegment('/data-center/versions/1')?.key).toBe('data')
    expect(activeFlowSegment('/factor-research')?.key).toBe('factor')
    expect(activeFlowSegment('/experiments/new')?.key).toBe('train')
    expect(activeFlowSegment('/models/abc/trade-workbench')?.key).toBe('train')
    expect(activeFlowSegment('/strategies')?.key).toBe('backtest')
    expect(activeFlowSegment('/predictions')?.key).toBe('backtest')
    expect(activeFlowSegment('/paper')?.key).toBe('paper')
  })

  it('leaves home, tasks and governance pages without a segment',()=>{
    expect(activeFlowSegment('/')).toBeNull()
    expect(activeFlowSegment('/jobs')).toBeNull()
    expect(activeFlowSegment('/admin/users')).toBeNull()
  })
})

describe('段内页签高亮',()=>{
  it('picks the longest matching tab',()=>{
    expect(activeSectionTab('/models/compare',{},trainingTabs)?.label).toBe('模型比较')
    expect(activeSectionTab('/models/3f2a1c',{},trainingTabs)?.label).toBe('模型仓库')
    expect(activeSectionTab('/datasets/new',{},trainingTabs)?.label).toBe('研究数据集')
    expect(activeSectionTab('/experiments',{},trainingTabs)?.label).toBe('训练实验')
    expect(activeSectionTab('/backtests/9',{},backtestTabs)?.label).toBe('回测中心')
    expect(activeSectionTab('/predictions',{},backtestTabs)?.label).toBe('批量预测')
  })

  it('separates same-path tabs by query',()=>{
    expect(activeSectionTab('/data-center',{},dataTabs)?.label).toBe('数据同步与版本')
    expect(activeSectionTab('/data-center',{focus:'snapshots'},dataTabs)?.label).toBe('因子快照')
    expect(activeSectionTab('/paper',{},paperTabs)?.label).toBe('账户总览')
    expect(activeSectionTab('/paper',{tab:'automation'},paperTabs)?.label).toBe('自动调仓')
    expect(activeSectionTab('/paper',{tab:'unknown'},paperTabs)?.label).toBe('账户总览')
  })

  it('returns nothing for paths outside the section',()=>{
    expect(activeSectionTab('/jobs',{},trainingTabs)).toBeNull()
  })
})
