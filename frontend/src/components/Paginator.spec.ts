import {mount} from '@vue/test-utils'
import {describe,expect,it} from 'vitest'
import Paginator from './Paginator.vue'

describe('Paginator',()=>{
  it('emits the next valid page',async()=>{
    const wrapper=mount(Paginator,{props:{page:1,total:45,pageSize:20}})
    const buttons=wrapper.findAll('button')
    expect(buttons[0].attributes('disabled')).toBeDefined()
    await buttons[1].trigger('click')
    expect(wrapper.emitted('change')?.[0]).toEqual([2])
    expect(wrapper.text()).toContain('第 1 / 3 页')
  })

  it('disables next on the final page',()=>{
    const wrapper=mount(Paginator,{props:{page:3,total:45,pageSize:20}})
    expect(wrapper.findAll('button')[1].attributes('disabled')).toBeDefined()
  })
})
