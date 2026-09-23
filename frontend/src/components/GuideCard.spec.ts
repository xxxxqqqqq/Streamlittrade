import {mount} from '@vue/test-utils'
import {describe,expect,it} from 'vitest'
import {Database} from 'lucide-vue-next'
import GuideCard from './GuideCard.vue'

describe('GuideCard',()=>{
  it('renders the page heading and the plain-language sentence',()=>{
    const wrapper=mount(GuideCard,{props:{title:'这一步在干什么',text:'选择股票池和时间范围，点同步，剩下的交给平台。'}})
    expect(wrapper.text()).toContain('这一步在干什么')
    expect(wrapper.text()).toContain('选择股票池和时间范围，点同步，剩下的交给平台。')
    expect(wrapper.classes()).toContain('guide-card')
  })

  it('uses the lucide icon a page passes in',()=>{
    expect(mount(GuideCard,{props:{title:'数据从哪来',text:'平台自动下载并质检。',icon:Database}}).find('.guide-icon svg').exists()).toBe(true)
  })

  it('falls back to a built-in glyph when no icon is given',()=>{
    const wrapper=mount(GuideCard,{props:{title:'这一步在干什么',text:'先看结论再看数字。'}})
    expect(wrapper.find('.guide-icon svg').exists()).toBe(false)
    expect(wrapper.find('.guide-icon').text()).not.toBe('')
  })
})
