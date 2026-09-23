import {describe,expect,it} from 'vitest'
import {
  VERDICT_COLORS,excessReturnVerdict,icDecayVerdict,rankIcVerdict,rocAucVerdict,selectionVerdict,
} from './verdict'

// 阈值是产品口径，这里逐条钉住边界：区间边界值必须落在高一级，避免改阈值时
// 悄悄改变结论，也防止页面各自重新实现判断。
describe('判断层 verdict',()=>{
  it('rocAucVerdict 按 0.60 / 0.55 / 0.52 分档',()=>{
    expect(rocAucVerdict(0.6).level).toBe('good')
    expect(rocAucVerdict(0.55).level).toBe('ok')
    expect(rocAucVerdict(0.52).level).toBe('weak')
    expect(rocAucVerdict(0.5199).level).toBe('bad')
    expect(rocAucVerdict(0.6).label).toBe('预测能力强')
    expect(rocAucVerdict(0.45).label).toBe('接近抛硬币')
    expect(rocAucVerdict(null).level).toBe('na')
    expect(rocAucVerdict(undefined).level).toBe('na')
    expect(rocAucVerdict(Number.NaN).level).toBe('na')
    expect(rocAucVerdict(null).label).toBe('无数据')
  })

  it('rankIcVerdict 按 |RankIC| 0.05 / 0.03 / 0.015 分档并标注反向',()=>{
    expect(rankIcVerdict(0.05).level).toBe('good')
    expect(rankIcVerdict(-0.05).label).toBe('反向有效')
    expect(rankIcVerdict(-0.05).level).toBe('good')
    expect(rankIcVerdict(0.03).level).toBe('ok')
    expect(rankIcVerdict(0.029).level).toBe('weak')
    expect(rankIcVerdict(0.015).level).toBe('weak')
    expect(rankIcVerdict(0.0149).level).toBe('bad')
    expect(rankIcVerdict(-0.0149).label).toBe('无效（反向）')
    expect(rankIcVerdict(0.004).label).toBe('无区分度')
    expect(rankIcVerdict(null).level).toBe('na')
  })

  it('icDecayVerdict 只在正向衰减时报警',()=>{
    expect(icDecayVerdict(-0.02).level).toBe('good')
    expect(icDecayVerdict(0).level).toBe('good')
    expect(icDecayVerdict(0.05).level).toBe('ok')
    expect(icDecayVerdict(0.0501).level).toBe('warn')
    expect(icDecayVerdict(0.0501).label).toBe('衰减明显')
    expect(icDecayVerdict(null).level).toBe('na')
  })

  it('excessReturnVerdict 按 ±5% 与 0 分档，并识别全现金',()=>{
    expect(excessReturnVerdict(0.05).level).toBe('good')
    expect(excessReturnVerdict(0.049).level).toBe('ok')
    expect(excessReturnVerdict(0).level).toBe('ok')
    expect(excessReturnVerdict(-0.001).level).toBe('weak')
    expect(excessReturnVerdict(-0.05).level).toBe('weak')
    expect(excessReturnVerdict(-0.0501).level).toBe('bad')
    expect(excessReturnVerdict(0.2,0).label).toBe('全现金（无入选）')
    expect(excessReturnVerdict(0.2,0).level).toBe('na')
    expect(excessReturnVerdict(0.2,null).level).toBe('good')
    expect(excessReturnVerdict(null).level).toBe('na')
  })

  it('selectionVerdict 只对“明确没有入选”给结论',()=>{
    expect(selectionVerdict(false)?.label).toBe('全现金（无入选）')
    expect(selectionVerdict(true)).toBeNull()
    expect(selectionVerdict(null)).toBeNull()
    expect(selectionVerdict(undefined)).toBeNull()
  })

  it('每个语义级别都有配色映射',()=>{
    expect(VERDICT_COLORS).toEqual({good:'g',ok:'p',warn:'w',weak:'w',bad:'b',na:'n'})
  })
})
