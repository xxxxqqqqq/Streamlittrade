import {mount} from '@vue/test-utils'
import {describe,expect,it} from 'vitest'
import StatusBadge from './StatusBadge.vue'

describe('StatusBadge',()=>{
  it('renders the chinese label and tone of a job status',()=>{
    const wrapper=mount(StatusBadge,{props:{status:'running'}})
    expect(wrapper.text()).toBe('运行中')
    expect(wrapper.classes()).toContain('running')
  })

  it('maps model stages and lifecycle states',()=>{
    expect(mount(StatusBadge,{props:{status:'production'}}).text()).toBe('生产中')
    expect(mount(StatusBadge,{props:{status:'archived'}}).text()).toBe('已归档')
    expect(mount(StatusBadge,{props:{status:'failed'}}).classes()).toContain('failed')
  })

  it('keeps an unknown value and allows an explicit label',()=>{
    expect(mount(StatusBadge,{props:{status:'unknown_stage'}}).text()).toBe('unknown_stage')
    expect(mount(StatusBadge,{props:{status:'enabled',label:'运行计划'}}).text()).toBe('运行计划')
    expect(mount(StatusBadge,{props:{status:null}}).text()).toBe('—')
  })
})
