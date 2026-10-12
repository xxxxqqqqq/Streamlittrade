import {describe,expect,it} from 'vitest'
import {labelModeLabel,selectionMetricLabel} from './labels'

// 翻译层是裸英文枚举的唯一出口：映射命中给中文，未命中一律空串（页面据此隐藏），
// 绝不能把原始枚举名渲染给用户。
describe('研究口径翻译层',()=>{
  it('把标签口径翻成一句人话',()=>{
    expect(labelModeLabel('executable_open_to_open_cross_sectional_v1')).toBe('标签口径：次日开盘买入的可执行收益 × 截面相对（跑赢当日中位数）')
  })

  it('未知或缺失的标签口径返回空串',()=>{
    expect(labelModeLabel('future_label_mode_v9')).toBe('')
    expect(labelModeLabel(null)).toBe('')
    expect(labelModeLabel(undefined)).toBe('')
  })

  it('网格搜索的选优口径走同一份映射',()=>{
    expect(selectionMetricLabel('tuning_folds_mean_rank_ic')).toBe('全部调参折的 OOS RankIC 均值')
    expect(selectionMetricLabel('some_other_metric')).toBe('')
  })
})
