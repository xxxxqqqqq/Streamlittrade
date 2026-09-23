import {describe,expect,it} from 'vitest'
import {jobKindLabel,jobSectionLabel,jobTarget} from './jobs'

describe('任务翻译层',()=>{
  it('把任务类型翻成中文，未知类型原样保留',()=>{
    expect(jobKindLabel('data_sync')).toBe('数据同步')
    expect(jobKindLabel('factor_research')).toBe('因子检验')
    expect(jobKindLabel('unknown_kind')).toBe('unknown_kind')
    expect(jobKindLabel(null)).toBe('未知任务')
    expect(jobSectionLabel('training')).toBe('训练')
    expect(jobSectionLabel('drift_monitor')).toBe('平台治理')
    expect(jobSectionLabel('unknown_kind')).toBe('其他')
  })

  it('按结果摘要里的实体 ID 给出产出物落点',()=>{
    expect(jobTarget({kind:'training',result_summary:{experiment_id:'e1',model_id:'m1'}})).toEqual({to:'/models/m1',label:'查看模型'})
    expect(jobTarget({kind:'data_sync',result_summary:{standard_version_id:'v1',rows:10}})).toEqual({to:'/data-center/versions/v1',label:'查看数据版本'})
    expect(jobTarget({kind:'feature_materialize',result_summary:{snapshot_id:'s1'}})).toEqual({to:'/data-center/snapshots/s1',label:'查看因子快照'})
    expect(jobTarget({kind:'dataset',result_summary:{dataset_id:'d1'}})).toEqual({to:'/datasets',label:'查看训练数据'})
    expect(jobTarget({kind:'paper_automation',result_summary:{run_id:'r1'}})).toEqual({to:'/paper',label:'查看模拟盘审计'})
  })

  it('回测任务的摘要是指标本身，按类型跳到回测中心',()=>{
    expect(jobTarget({kind:'backtest',result_summary:{model_id:'m1',excess_return:-3.81}})).toEqual({to:'/backtests',label:'查看回测报告'})
    expect(jobTarget({kind:'drift_monitor',result_summary:{drift_run_id:'d1'}})).toEqual({to:'/monitoring',label:'查看漂移监控'})
  })

  it('没有产出物时不编跳转目标',()=>{
    expect(jobTarget({kind:'training',result_summary:null})).toBeNull()
    expect(jobTarget({kind:'training',status:'running'} as any)).toBeNull()
    expect(jobTarget(null)).toBeNull()
  })
})
