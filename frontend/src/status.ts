// 状态与阶段英文枚举的唯一映射：StatusBadge 用它渲染徽标，下拉筛选用它
// 显示同一个中文叫法，避免同一枚举在不同页面出现两种名字或裸英文。
export const STATUS_LABELS:Record<string,string>={
  queued:'排队中',running:'运行中',cancel_requested:'取消中',canceled:'已取消',
  succeeded:'成功',failed:'失败',
  ready:'已就绪',pending:'准备中',
  candidate:'候选',validated:'已验证',production:'生产中',archived:'已归档',
  enabled:'已启用',paused:'已暂停',active:'正常',frozen:'已冻结',disabled:'已停用',
  eligible:'可通过',blocked:'被拦截',
  proposed:'待复核',filled:'已成交',rejected:'已拒绝',
}

const STATUS_TONES:Record<string,string>={
  queued:'pending',running:'running',cancel_requested:'pending',canceled:'canceled',
  succeeded:'succeeded',failed:'failed',
  ready:'succeeded',pending:'pending',
  candidate:'candidate',validated:'validated',production:'production',archived:'archived',
  enabled:'succeeded',paused:'archived',active:'succeeded',frozen:'archived',disabled:'archived',
  eligible:'succeeded',blocked:'failed',
  proposed:'pending',filled:'succeeded',rejected:'failed',
}

export function statusLabel(status?:string|null){
  const value=String(status??'')
  return STATUS_LABELS[value]||value
}

export function statusTone(status?:string|null){
  return STATUS_TONES[String(status??'')]||''
}
