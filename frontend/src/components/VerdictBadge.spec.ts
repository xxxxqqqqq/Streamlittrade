import {mount} from '@vue/test-utils'
import {describe,expect,it} from 'vitest'
import {excessReturnVerdict,rankIcVerdict,rocAucVerdict} from '../verdict'
import VerdictBadge from './VerdictBadge.vue'

describe('VerdictBadge',()=>{
  it('renders the verdict text with its glyph',()=>{
    expect(mount(VerdictBadge,{props:{verdict:rankIcVerdict(0.056)}}).text()).toBe('✓ 有效')
    expect(mount(VerdictBadge,{props:{verdict:rocAucVerdict(0.45)}}).text()).toBe('✗ 接近抛硬币')
    expect(mount(VerdictBadge,{props:{verdict:rankIcVerdict(0.018)}}).text()).toBe('— 偏弱')
  })

  it('maps every level through VERDICT_COLORS',()=>{
    expect(mount(VerdictBadge,{props:{verdict:rankIcVerdict(0.056)}}).classes()).toContain('g')
    expect(mount(VerdictBadge,{props:{verdict:rocAucVerdict(0.57)}}).classes()).toContain('p')
    expect(mount(VerdictBadge,{props:{verdict:rankIcVerdict(0.018)}}).classes()).toContain('w')
    expect(mount(VerdictBadge,{props:{verdict:excessReturnVerdict(-0.08)}}).classes()).toContain('b')
  })

  it('shows the threshold basis as hover hint',()=>{
    expect(mount(VerdictBadge,{props:{verdict:rankIcVerdict(0.056)}}).attributes('title')).toBe('|RankIC| ≥ 0.05，强区分度')
  })

  it('keeps 无数据 neutral and renders nothing without a verdict',()=>{
    const missing=mount(VerdictBadge,{props:{verdict:rocAucVerdict(null)}})
    expect(missing.text()).toBe('· 无数据')
    expect(missing.classes()).toContain('n')
    expect(missing.classes()).not.toContain('b')
    expect(mount(VerdictBadge,{props:{verdict:null}}).find('.verdict-badge').exists()).toBe(false)
  })
})
