// 指标判断层（Verdict）：把机器指标翻译成"好/弱/差"的唯一实现。
// 阈值是产品决策，只许在这里改；页面一律使用本模块，不得各自写判断逻辑。

export type VerdictLevel = 'good' | 'ok' | 'warn' | 'weak' | 'bad' | 'na'

export interface Verdict {
  level: VerdictLevel
  label: string        // 中文判断短语
  hint: string         // 阈值依据（tooltip）
}

// 预测能力（ROC AUC，截面相对标签下 0.5 为抛硬币）
export function rocAucVerdict(value: number | null | undefined): Verdict {
  if (value == null || Number.isNaN(value)) return {level: 'na', label: '无数据', hint: ''}
  if (value >= 0.6) return {level: 'good', label: '预测能力强', hint: 'ROC AUC ≥ 0.60'}
  if (value >= 0.55) return {level: 'ok', label: '有预测信号', hint: 'ROC AUC ≥ 0.55'}
  if (value >= 0.52) return {level: 'weak', label: '信号偏弱', hint: '0.52 ≤ ROC AUC < 0.55'}
  return {level: 'bad', label: '接近抛硬币', hint: 'ROC AUC < 0.52，不具备可用信号'}
}

// 选股区分度（RankIC 均值）
export function rankIcVerdict(value: number | null | undefined): Verdict {
  if (value == null || Number.isNaN(value)) return {level: 'na', label: '无数据', hint: ''}
  const abs = Math.abs(value)
  const dir = value < 0 ? '反向' : ''
  if (abs >= 0.05) return {level: 'good', label: `${dir}有效`, hint: '|RankIC| ≥ 0.05，强区分度'}
  if (abs >= 0.03) return {level: 'ok', label: `${dir}有效`, hint: '|RankIC| ≥ 0.03，可用区分度'}
  if (abs >= 0.015) return {level: 'weak', label: '偏弱', hint: '|RankIC| < 0.03，区分度不足'}
  return {level: 'bad', label: value < 0 ? '无效（反向）' : '无区分度', hint: '|RankIC| < 0.015'}
}

// 信号衰减（首末折 RankIC 差；越大越危险）
export function icDecayVerdict(value: number | null | undefined): Verdict {
  if (value == null || Number.isNaN(value)) return {level: 'na', label: '无数据', hint: ''}
  if (value <= 0) return {level: 'good', label: '未见衰减', hint: '近期折不弱于早期折'}
  if (value <= 0.05) return {level: 'ok', label: '轻微衰减', hint: '首末折 RankIC 差 ≤ 0.05'}
  return {level: 'warn', label: '衰减明显', hint: '首末折 RankIC 差 > 0.05，信号在时间上变弱'}
}

// 回测结论：相对基准的超额收益（小数，如 -0.038）
export function excessReturnVerdict(value: number | null | undefined, trades?: number | null): Verdict {
  if (trades === 0) return {level: 'na', label: '全现金（无入选）', hint: '没有标的达到预登记入选线，这是有效结论'}
  if (value == null || Number.isNaN(value)) return {level: 'na', label: '无数据', hint: ''}
  if (value >= 0.05) return {level: 'good', label: '跑赢基准', hint: '超额收益 ≥ 5%'}
  if (value >= 0) return {level: 'ok', label: '小幅跑赢', hint: '超额收益 ≥ 0'}
  if (value >= -0.05) return {level: 'weak', label: '小幅跑输', hint: '超额收益 < 0'}
  return {level: 'bad', label: '跑输基准', hint: '超额收益 ≤ -5%'}
}

// 全现金等特殊状态
export function selectionVerdict(hasSelections: boolean | null | undefined): Verdict | null {
  if (hasSelections === false) return {level: 'na', label: '全现金（无入选）', hint: '阈值内无标的入选，平台按有效结论处理'}
  return null
}

// 判断级别到 StatusBadge 配色的映射
export const VERDICT_COLORS: Record<VerdictLevel, string> = {
  good: 'g', ok: 'p', warn: 'w', weak: 'w', bad: 'b', na: 'n',
}
