// 任务翻译层：任务类型、所属研究段与产出物落点的唯一映射。任务中心和控制台
// 共用这一份，避免同一个 kind 在两处出现两种叫法、或指向两个不同的产出物。
export interface JobLike {
  kind?:string|null
  result_summary?:Record<string,any>|null
}

export const JOB_KIND_LABELS:Record<string,string>={
  data_sync:'数据同步',feature_materialize:'因子快照物化',factor_research:'因子检验',
  dataset:'训练数据构建',training:'模型训练',sealed_evaluation:'终检评估',
  backtest:'组合回测',prediction:'批量预测',paper_automation:'模拟盘调仓',drift_monitor:'漂移监控',
}

export const JOB_SECTION_LABELS:Record<string,string>={
  data_sync:'获取数据',feature_materialize:'获取数据',factor_research:'因子',
  dataset:'训练',training:'训练',sealed_evaluation:'训练',
  backtest:'回测',prediction:'回测',paper_automation:'模拟盘',drift_monitor:'平台治理',
}

export function jobKindLabel(kind?:string|null){
  const value=String(kind??'')
  return JOB_KIND_LABELS[value]||value||'未知任务'
}

export function jobSectionLabel(kind?:string|null){
  return JOB_SECTION_LABELS[String(kind??'')]||'其他'
}

// 产出物落点只看任务结果里登记的实体 ID。回测任务的结果摘要是账本指标本身
// （里面也带 model_id），所以先按类型判断，避免把回测任务错跳到模型详情。
export function jobTarget(job:JobLike|null|undefined):{to:string;label:string}|null{
  if(!job)return null
  if(job.kind==='backtest')return{to:'/backtests',label:'查看回测报告'}
  if(job.kind==='drift_monitor')return{to:'/monitoring',label:'查看漂移监控'}
  const summary=job.result_summary||{}
  if(summary.standard_version_id)return{to:`/data-center/versions/${summary.standard_version_id}`,label:'查看数据版本'}
  if(summary.snapshot_id)return{to:`/data-center/snapshots/${summary.snapshot_id}`,label:'查看因子快照'}
  if(summary.factor_research_id)return{to:'/factor-research',label:'查看因子检验'}
  if(summary.dataset_id)return{to:'/datasets',label:'查看训练数据'}
  if(summary.model_id)return{to:`/models/${summary.model_id}`,label:'查看模型'}
  if(summary.experiment_id)return{to:'/experiments',label:'查看训练实验'}
  if(summary.prediction_id)return{to:'/predictions',label:'查看批量预测'}
  if(summary.run_id)return{to:'/paper',label:'查看模拟盘审计'}
  return null
}
