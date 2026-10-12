// 研究口径与选参过程的翻译层：后端写在 JSON 里的英文枚举只在这里映射成中文，
// 页面统一调用本模块。未知取值返回空串，由页面隐藏，绝不把原始枚举名渲染给用户。

// 标签口径：平台按"次日开盘买入、截面相对强弱"造标签，这句话要在页面上说得清楚。
export const LABEL_MODE_LABELS:Record<string,string>={
  executable_open_to_open_cross_sectional_v1:'标签口径：次日开盘买入的可执行收益 × 截面相对（跑赢当日中位数）',
}

export function labelModeLabel(mode?:string|null){
  return LABEL_MODE_LABELS[String(mode??'')]||''
}

// 网格搜索的选优口径：后端记录"在哪些折上比、按哪个指标比"。
export const SELECTION_METRIC_LABELS:Record<string,string>={
  tuning_folds_mean_rank_ic:'全部调参折的 OOS RankIC 均值',
}

export function selectionMetricLabel(metric?:string|null){
  return SELECTION_METRIC_LABELS[String(metric??'')]||''
}
