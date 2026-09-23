import {mount} from '@vue/test-utils'
import {describe,expect,it} from 'vitest'
import VerdictCard from './VerdictCard.vue'

describe('VerdictCard',()=>{
  it('colours the card by the verdict level',()=>{
    expect(mount(VerdictCard,{props:{level:'good'}}).classes()).toContain('good')
    expect(mount(VerdictCard,{props:{level:'warn'}}).classes()).toContain('warn')
    expect(mount(VerdictCard,{props:{level:'bad'}}).classes()).toContain('bad')
  })

  it('keeps 无数据 / 全现金 neutral instead of red',()=>{
    expect(mount(VerdictCard,{props:{level:'na'}}).classes()).toContain('na')
    expect(mount(VerdictCard,{props:{level:'na'}}).classes()).not.toContain('bad')
  })

  it('falls back to a neutral tier when no level is known',()=>{
    expect(mount(VerdictCard).classes()).toContain('na')
  })

  it('renders the conclusion sentence and explanation from the slot',()=>{
    const wrapper=mount(VerdictCard,{props:{level:'bad'},slots:{default:'<b>结论：这个模型目前不赚钱</b><p>跑输基准 3.8 个点。</p>'}})
    expect(wrapper.text()).toContain('结论：这个模型目前不赚钱')
    expect(wrapper.text()).toContain('跑输基准 3.8 个点。')
  })
})
